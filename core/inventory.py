"""
Inventory domain services.

This module implements atomic, idempotent inventory workflows for checkout and order
lifecycle transitions.

Design:
- Item has two counters:
  - stock_on_hand: physical stock available in the warehouse
  - stock_reserved: stock allocated to un-paid/un-fulfilled orders
- During checkout/payment intent:
  - reserve: move units from available -> reserved (increments stock_reserved)
- On payment success:
  - commit: convert reserved into sale (decrement stock_on_hand and stock_reserved)
- On cancel / payment failure:
  - release: remove reservation (decrement stock_reserved)
- On refund/return:
  - restock: increase stock_on_hand (and record an InventoryAdjustment)

All write operations lock Item rows with SELECT ... FOR UPDATE to avoid overselling.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import InventoryAdjustment, Item, Order, OrderItem


@dataclass(frozen=True)
class InventoryActionResult:
    """Result for inventory operations."""

    changed: bool
    detail: str


def _ensure_non_negative(value: int, *, field: str) -> None:
    if value < 0:
        raise ValidationError(f"{field} cannot be negative")


# PUBLIC_INTERFACE
def reserve_inventory_for_order(
    *,
    order: Order,
    performed_by=None,
    idempotency_key: str | None = None,
) -> InventoryActionResult:
    """
    PUBLIC_INTERFACE
    Reserve inventory for all OrderItems in an order.

    This atomically increases Item.stock_reserved while ensuring that available_stock
    is not exceeded.

    Idempotency:
    - For each OrderItem, we only reserve the delta between required quantity and
      already-reserved quantity (OrderItem.quantity_reserved).
    - Repeated calls are safe.

    Raises:
      ValidationError if there is insufficient stock for any item.
    """
    if order.pk is None:
        raise ValidationError("Order must be saved before reserving inventory.")

    # We do not reserve for already-cancelled/refunded orders.
    if order.status in {Order.Status.CANCELLED, Order.Status.REFUNDED}:
        return InventoryActionResult(
            changed=False, detail=f"Order status {order.status} not reservable."
        )

    order_items: list[OrderItem] = list(order.items.select_related("item").all())
    if not order_items:
        return InventoryActionResult(changed=False, detail="Order has no items.")

    with transaction.atomic():
        # Lock items in a stable order to avoid deadlocks.
        item_ids = sorted({oi.item_id for oi in order_items})
        locked_items = {
            it.id: it for it in Item.objects.select_for_update().filter(id__in=item_ids)
        }

        changed_any = False

        for oi in order_items:
            item = locked_items[oi.item_id]
            required = int(oi.quantity or 0)
            already_reserved = int(oi.quantity_reserved or 0)
            _ensure_non_negative(required, field="OrderItem.quantity")
            _ensure_non_negative(already_reserved, field="OrderItem.quantity_reserved")

            if already_reserved > required:
                # If cart quantity was reduced after reservation, release the excess to remain consistent.
                excess = already_reserved - required
                if excess > 0:
                    if item.stock_reserved < excess:
                        raise ValidationError(
                            f"Inventory invariant violation for item={item.id}: reserved below excess release."
                        )
                    item.stock_reserved -= excess
                    oi.quantity_reserved -= excess
                    item.save(update_fields=["stock_reserved"])
                    oi.save(update_fields=["quantity_reserved"])
                    changed_any = True
                continue

            delta_to_reserve = required - already_reserved
            if delta_to_reserve <= 0:
                continue

            if item.available_stock < delta_to_reserve:
                raise ValidationError(
                    f"Insufficient stock for '{item.title}'. Requested {delta_to_reserve}, available {item.available_stock}."
                )

            item.stock_reserved += delta_to_reserve
            oi.quantity_reserved += delta_to_reserve
            item.save(update_fields=["stock_reserved"])
            oi.save(update_fields=["quantity_reserved"])
            changed_any = True

        if changed_any:
            return InventoryActionResult(changed=True, detail="Reserved inventory.")
        return InventoryActionResult(
            changed=False, detail="No reservation changes required (already reserved)."
        )


# PUBLIC_INTERFACE
def release_inventory_reservations_for_order(
    *,
    order: Order,
    performed_by=None,
    idempotency_key: str | None = None,
    reason: str = "Reservation released",
) -> InventoryActionResult:
    """
    PUBLIC_INTERFACE
    Release (rollback) all remaining reservations for an order.

    This decreases Item.stock_reserved based on OrderItem.quantity_reserved and sets
    OrderItem.quantity_reserved to 0. Safe for repeats.

    Notes:
    - This does NOT change stock_on_hand.
    """
    order_items: list[OrderItem] = list(order.items.select_related("item").all())
    if not order_items:
        return InventoryActionResult(changed=False, detail="Order has no items.")

    with transaction.atomic():
        item_ids = sorted({oi.item_id for oi in order_items})
        locked_items = {
            it.id: it for it in Item.objects.select_for_update().filter(id__in=item_ids)
        }

        changed_any = False

        for oi in order_items:
            reserved = int(oi.quantity_reserved or 0)
            _ensure_non_negative(reserved, field="OrderItem.quantity_reserved")
            if reserved == 0:
                continue

            item = locked_items[oi.item_id]
            if item.stock_reserved < reserved:
                raise ValidationError(
                    f"Inventory invariant violation for item={item.id}: stock_reserved < quantity_reserved."
                )

            item.stock_reserved -= reserved
            oi.quantity_reserved = 0
            item.save(update_fields=["stock_reserved"])
            oi.save(update_fields=["quantity_reserved"])
            changed_any = True

        if changed_any:
            return InventoryActionResult(changed=True, detail=reason)
        return InventoryActionResult(
            changed=False, detail="No reservations to release."
        )


# PUBLIC_INTERFACE
def commit_inventory_for_paid_order(
    *,
    order: Order,
    performed_by=None,
    idempotency_key: str | None = None,
) -> InventoryActionResult:
    """
    PUBLIC_INTERFACE
    Commit inventory for an order that has successfully been paid.

    Converts reserved stock to a sale:
      - Item.stock_reserved decreases by reserved amount
      - Item.stock_on_hand decreases by the same amount
      - InventoryAdjustment is recorded with delta = -qty and reason=SALE

    Idempotency:
    - For each OrderItem, commit only the delta between quantity_reserved and quantity_committed.
    - Safe for repeated calls (e.g., payment retries/callback duplication).

    Raises:
      ValidationError if reservation/stock invariants do not hold.
    """
    order_items: list[OrderItem] = list(order.items.select_related("item").all())
    if not order_items:
        return InventoryActionResult(changed=False, detail="Order has no items.")

    with transaction.atomic():
        item_ids = sorted({oi.item_id for oi in order_items})
        locked_items = {
            it.id: it for it in Item.objects.select_for_update().filter(id__in=item_ids)
        }

        changed_any = False

        for oi in order_items:
            reserved = int(oi.quantity_reserved or 0)
            committed = int(oi.quantity_committed or 0)
            _ensure_non_negative(reserved, field="OrderItem.quantity_reserved")
            _ensure_non_negative(committed, field="OrderItem.quantity_committed")

            if committed > reserved:
                raise ValidationError(
                    "OrderItem.quantity_committed cannot exceed quantity_reserved."
                )

            delta_to_commit = reserved - committed
            if delta_to_commit <= 0:
                continue

            item = locked_items[oi.item_id]
            if item.stock_reserved < delta_to_commit:
                raise ValidationError(
                    f"Inventory invariant violation for item={item.id}: stock_reserved < commit delta."
                )
            if item.stock_on_hand < delta_to_commit:
                raise ValidationError(
                    f"Inventory invariant violation for item={item.id}: stock_on_hand < commit delta."
                )

            item.stock_reserved -= delta_to_commit
            item.stock_on_hand -= delta_to_commit
            oi.quantity_committed += delta_to_commit

            item.save(update_fields=["stock_reserved", "stock_on_hand"])
            oi.save(update_fields=["quantity_committed"])

            InventoryAdjustment.objects.create(
                item=item,
                delta=-delta_to_commit,
                reason=InventoryAdjustment.Reason.SALE,
                created_by=performed_by,
                note=f"Committed sale for order={order.id} (idempotency_key={idempotency_key})",
            )
            changed_any = True

        if changed_any:
            return InventoryActionResult(
                changed=True, detail="Committed inventory for paid order."
            )
        return InventoryActionResult(
            changed=False, detail="No inventory commit required (already committed)."
        )


# PUBLIC_INTERFACE
def restock_inventory_for_order_refund(
    *,
    order: Order,
    performed_by=None,
    idempotency_key: str | None = None,
) -> InventoryActionResult:
    """
    PUBLIC_INTERFACE
    Restock inventory for a refunded order.

    This assumes the order had been committed (stock_on_hand decremented) and we now
    need to reverse that (stock_on_hand incremented).

    Idempotency:
    - Only restock the delta between quantity_committed and quantity_restocked.
    - Safe for repeated calls.

    Note:
    - This does not touch stock_reserved; refunds happen after payment.
    """
    order_items: list[OrderItem] = list(order.items.select_related("item").all())
    if not order_items:
        return InventoryActionResult(changed=False, detail="Order has no items.")

    with transaction.atomic():
        item_ids = sorted({oi.item_id for oi in order_items})
        locked_items = {
            it.id: it for it in Item.objects.select_for_update().filter(id__in=item_ids)
        }

        changed_any = False

        for oi in order_items:
            committed = int(oi.quantity_committed or 0)
            restocked = int(oi.quantity_restocked or 0)
            _ensure_non_negative(committed, field="OrderItem.quantity_committed")
            _ensure_non_negative(restocked, field="OrderItem.quantity_restocked")

            if restocked > committed:
                raise ValidationError(
                    "OrderItem.quantity_restocked cannot exceed quantity_committed."
                )

            delta_to_restock = committed - restocked
            if delta_to_restock <= 0:
                continue

            item = locked_items[oi.item_id]
            item.stock_on_hand += delta_to_restock
            oi.quantity_restocked += delta_to_restock

            item.save(update_fields=["stock_on_hand"])
            oi.save(update_fields=["quantity_restocked"])

            InventoryAdjustment.objects.create(
                item=item,
                delta=delta_to_restock,
                reason=InventoryAdjustment.Reason.RETURN,
                created_by=performed_by,
                note=f"Restocked for refund order={order.id} (idempotency_key={idempotency_key})",
            )
            changed_any = True

        if changed_any:
            return InventoryActionResult(
                changed=True, detail="Restocked inventory for refunded order."
            )
        return InventoryActionResult(
            changed=False, detail="No restock required (already restocked)."
        )
