import pytest
from django.core.exceptions import ValidationError

from core.inventory import (commit_inventory_for_paid_order,
                            release_inventory_reservations_for_order,
                            reserve_inventory_for_order,
                            restock_inventory_for_order_refund)
from core.models import InventoryAdjustment


@pytest.mark.django_db
def test_inventory_reserve_commit_restock_idempotency(
    item_factory, order_factory, user
):
    item = item_factory(stock_on_hand=10, stock_reserved=0)
    order, oi = order_factory(
        user=user, item=item, quantity=3, status="CREATED", ordered=False
    )

    # Reserve
    res1 = reserve_inventory_for_order(
        order=order, performed_by=user, idempotency_key="t1"
    )
    assert res1.changed is True
    item.refresh_from_db()
    oi.refresh_from_db()
    assert item.stock_reserved == 3
    assert oi.quantity_reserved == 3
    assert item.stock_on_hand == 10  # reservation doesn't change on_hand

    # Reserve again: idempotent
    res2 = reserve_inventory_for_order(
        order=order, performed_by=user, idempotency_key="t1"
    )
    assert res2.changed is False
    item.refresh_from_db()
    assert item.stock_reserved == 3

    # Commit
    before_adj = InventoryAdjustment.objects.count()
    com1 = commit_inventory_for_paid_order(
        order=order, performed_by=user, idempotency_key="t2"
    )
    assert com1.changed is True
    item.refresh_from_db()
    oi.refresh_from_db()
    assert item.stock_reserved == 0
    assert item.stock_on_hand == 7
    assert oi.quantity_committed == 3
    assert InventoryAdjustment.objects.count() == before_adj + 1

    # Commit again: idempotent (no extra adjustments)
    com2 = commit_inventory_for_paid_order(
        order=order, performed_by=user, idempotency_key="t2"
    )
    assert com2.changed is False
    assert InventoryAdjustment.objects.count() == before_adj + 1

    # Restock (refund)
    rest1 = restock_inventory_for_order_refund(
        order=order, performed_by=user, idempotency_key="t3"
    )
    assert rest1.changed is True
    item.refresh_from_db()
    oi.refresh_from_db()
    assert item.stock_on_hand == 10
    assert oi.quantity_restocked == 3

    # Restock again: idempotent
    rest2 = restock_inventory_for_order_refund(
        order=order, performed_by=user, idempotency_key="t3"
    )
    assert rest2.changed is False


@pytest.mark.django_db
def test_inventory_release_reservation_idempotent(item_factory, order_factory, user):
    item = item_factory(stock_on_hand=5, stock_reserved=0)
    order, oi = order_factory(
        user=user, item=item, quantity=2, status="CREATED", ordered=False
    )

    reserve_inventory_for_order(order=order, performed_by=user, idempotency_key="r1")
    item.refresh_from_db()
    assert item.stock_reserved == 2

    rel1 = release_inventory_reservations_for_order(
        order=order, performed_by=user, idempotency_key="rel", reason="x"
    )
    assert rel1.changed is True
    item.refresh_from_db()
    oi.refresh_from_db()
    assert item.stock_reserved == 0
    assert oi.quantity_reserved == 0

    rel2 = release_inventory_reservations_for_order(
        order=order, performed_by=user, idempotency_key="rel", reason="x"
    )
    assert rel2.changed is False


@pytest.mark.django_db
def test_inventory_reserve_insufficient_stock_raises(item_factory, order_factory, user):
    item = item_factory(stock_on_hand=1, stock_reserved=0)
    order, _oi = order_factory(
        user=user, item=item, quantity=2, status="CREATED", ordered=False
    )

    with pytest.raises(ValidationError):
        reserve_inventory_for_order(
            order=order, performed_by=user, idempotency_key="nope"
        )
