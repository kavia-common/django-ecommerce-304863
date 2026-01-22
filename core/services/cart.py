"""Cart and order related business logic.

These helpers are designed to be unit-testable and to keep Django views thin.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import Item, Order, OrderItem


@dataclass(frozen=True)
class CartResult:
    """Result of a cart operation (message + optional redirect hint)."""

    message: str
    redirect_name: str
    redirect_kwargs: dict | None = None


# PUBLIC_INTERFACE
def add_item_to_cart(*, user: get_user_model(), item: Item) -> CartResult:
    """Add an item to the user's active cart (or create a new order).

    Behavior matches the original view logic:
    - If active order exists and item is already in it: increment quantity and redirect to order summary.
    - If active order exists and item not in it: add new OrderItem and redirect to order summary.
    - If no active order: create order and add item; redirect to order summary.
    """
    order_item, _created = OrderItem.objects.get_or_create(
        item=item, user=user, ordered=False
    )

    order_qs = Order.objects.filter(user=user, ordered=False)
    if order_qs.exists():
        order = order_qs[0]
        if order.items.filter(item__slug=item.slug).exists():
            order_item.quantity += 1
            order_item.save()
            return CartResult(
                message="This item quantity was updated.",
                redirect_name="core:order-summary",
            )

        order.items.add(order_item)
        return CartResult(
            message="This item was added to your cart.",
            redirect_name="core:order-summary",
        )

    ordered_date = timezone.now()
    order = Order.objects.create(user=user, ordered_date=ordered_date)
    order.items.add(order_item)
    return CartResult(
        message="This item was added to your cart.",
        redirect_name="core:order-summary",
    )


# PUBLIC_INTERFACE
def remove_item_from_cart(*, user: get_user_model(), item: Item) -> CartResult:
    """Remove an item entirely from the user's active cart."""
    order_qs = Order.objects.filter(user=user, ordered=False)
    if not order_qs.exists():
        return CartResult(
            message="You do not have an active order",
            redirect_name="core:product",
            redirect_kwargs={"slug": item.slug},
        )

    order = order_qs[0]
    if not order.items.filter(item__slug=item.slug).exists():
        return CartResult(
            message="This item was not in your cart",
            redirect_name="core:product",
            redirect_kwargs={"slug": item.slug},
        )

    order_item = OrderItem.objects.filter(item=item, user=user, ordered=False)[0]
    order.items.remove(order_item)
    order_item.delete()
    return CartResult(
        message="This item was removed from your cart.",
        redirect_name="core:order-summary",
    )


# PUBLIC_INTERFACE
def remove_single_quantity_from_cart(
    *, user: get_user_model(), item: Item
) -> CartResult:
    """Remove a single quantity of an item from the cart (or remove the item if qty becomes 0)."""
    order_qs = Order.objects.filter(user=user, ordered=False)
    if not order_qs.exists():
        return CartResult(
            message="You do not have an active order",
            redirect_name="core:product",
            redirect_kwargs={"slug": item.slug},
        )

    order = order_qs[0]
    if not order.items.filter(item__slug=item.slug).exists():
        return CartResult(
            message="This item was not in your cart",
            redirect_name="core:product",
            redirect_kwargs={"slug": item.slug},
        )

    order_item = OrderItem.objects.filter(item=item, user=user, ordered=False)[0]
    if order_item.quantity > 1:
        order_item.quantity -= 1
        order_item.save()
    else:
        order.items.remove(order_item)

    return CartResult(
        message="This item quantity was updated.",
        redirect_name="core:order-summary",
    )
