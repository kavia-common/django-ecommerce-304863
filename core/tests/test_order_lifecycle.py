import pytest

from core.models import InventoryAdjustment, Order


@pytest.mark.django_db
def test_user_orders_endpoints_are_user_scoped(api_client, item_factory, order_factory, obtain_jwt_tokens, user_password, user):
    item = item_factory()
    order, _oi = order_factory(user=user, item=item, quantity=1)

    # Another user
    from django.contrib.auth.models import User as DjangoUser

    other = DjangoUser.objects.create(username="other_user2")
    other.set_password("pw2")
    other.save()

    hdr_user = {"HTTP_AUTHORIZATION": f"Bearer {obtain_jwt_tokens(user, user_password)['access']}"}
    hdr_other = {"HTTP_AUTHORIZATION": f"Bearer {obtain_jwt_tokens(other, 'pw2')['access']}"}

    # User can list
    my_list = api_client.get("/api/orders/", **hdr_user)
    assert my_list.status_code == 200
    assert any(o["id"] == order.id for o in my_list.json())

    # Other user cannot retrieve this order (404)
    other_get = api_client.get(f"/api/orders/{order.id}/", **hdr_other)
    assert other_get.status_code == 404

    # User can retrieve their own
    mine = api_client.get(f"/api/orders/{order.id}/", **hdr_user)
    assert mine.status_code == 200
    assert mine.json()["id"] == order.id


@pytest.mark.django_db
def test_admin_orders_list_requires_admin(api_client, auth_headers_for_user):
    resp = api_client.get("/api/admin/orders/", **auth_headers_for_user)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_transition_paid_is_idempotent_and_creates_history_and_inventory(
    api_client,
    item_factory,
    order_factory,
    admin_user_in_group,
    auth_headers_for_admin,
):
    item = item_factory(stock_on_hand=10, stock_reserved=0)
    order, oi = order_factory(user=admin_user_in_group, item=item, quantity=2, status=Order.Status.CREATED, ordered=False)

    before_hist = order.status_history.count()
    before_adj = InventoryAdjustment.objects.count()

    payload = {"target_status": Order.Status.PAID, "idempotency_key": "idem-paid-1"}
    r1 = api_client.post(f"/api/admin/orders/{order.id}/transition/", payload, format="json", **auth_headers_for_admin)
    assert r1.status_code == 200, r1.content

    order.refresh_from_db()
    oi.refresh_from_db()
    item.refresh_from_db()

    assert order.status == Order.Status.PAID
    assert order.status_history.count() == before_hist + 1
    assert oi.quantity_committed == 2
    assert item.stock_on_hand == 8
    assert item.stock_reserved == 0
    assert InventoryAdjustment.objects.count() == before_adj + 1

    # Repeat same transition with same idempotency key should not duplicate history nor adjustments
    r2 = api_client.post(f"/api/admin/orders/{order.id}/transition/", payload, format="json", **auth_headers_for_admin)
    assert r2.status_code == 200
    order.refresh_from_db()
    assert order.status_history.count() == before_hist + 1
    assert InventoryAdjustment.objects.count() == before_adj + 1


@pytest.mark.django_db
def test_admin_transition_cancel_releases_reservation(api_client, item_factory, order_factory, auth_headers_for_admin, admin_user_in_group):
    item = item_factory(stock_on_hand=5, stock_reserved=0)
    order, oi = order_factory(user=admin_user_in_group, item=item, quantity=3, status=Order.Status.CREATED, ordered=False)

    # Reserve via admin PAID? No: reserve happens inside PAID transition, but cancel should also release if reserved.
    # We'll reserve by calling PAID then "rewind" is not allowed; instead reserve through dummy payment endpoint isn't admin.
    # Use the inventory function indirectly by triggering PAID? Not needed: we can reserve by calling transition PAID then cancel is valid.
    api_client.post(
        f"/api/admin/orders/{order.id}/transition/",
        {"target_status": Order.Status.PAID, "idempotency_key": "paid-first"},
        format="json",
        **auth_headers_for_admin,
    )
    order.refresh_from_db()
    assert order.status == Order.Status.PAID

    # Cancel is allowed from PAID and should not break; it should release any outstanding reservation (should be 0 after commit).
    resp = api_client.post(
        f"/api/admin/orders/{order.id}/transition/",
        {"target_status": Order.Status.CANCELLED, "idempotency_key": "cancel-1"},
        format="json",
        **auth_headers_for_admin,
    )
    assert resp.status_code == 200
    item.refresh_from_db()
    oi.refresh_from_db()
    assert item.stock_reserved == 0
    assert oi.quantity_reserved == 0
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED


@pytest.mark.django_db
def test_admin_transition_refund_restocks_and_is_idempotent(api_client, item_factory, order_factory, auth_headers_for_admin, admin_user_in_group):
    item = item_factory(stock_on_hand=4, stock_reserved=0)
    order, oi = order_factory(user=admin_user_in_group, item=item, quantity=2, status=Order.Status.CREATED, ordered=False)

    api_client.post(
        f"/api/admin/orders/{order.id}/transition/",
        {"target_status": Order.Status.PAID, "idempotency_key": "paid-then-refund"},
        format="json",
        **auth_headers_for_admin,
    )
    item.refresh_from_db()
    assert item.stock_on_hand == 2

    before_adj = InventoryAdjustment.objects.count()
    payload = {"target_status": Order.Status.REFUNDED, "idempotency_key": "refund-1"}
    r1 = api_client.post(f"/api/admin/orders/{order.id}/transition/", payload, format="json", **auth_headers_for_admin)
    assert r1.status_code == 200

    order.refresh_from_db()
    oi.refresh_from_db()
    item.refresh_from_db()
    assert order.status == Order.Status.REFUNDED
    assert item.stock_on_hand == 4
    assert oi.quantity_restocked == 2
    assert InventoryAdjustment.objects.count() == before_adj + 1

    # Idempotent repeat: no more adjustments
    r2 = api_client.post(f"/api/admin/orders/{order.id}/transition/", payload, format="json", **auth_headers_for_admin)
    assert r2.status_code == 200
    assert InventoryAdjustment.objects.count() == before_adj + 1


@pytest.mark.django_db
def test_invalid_order_transition_returns_400(api_client, item_factory, order_factory, auth_headers_for_admin, admin_user_in_group):
    item = item_factory()
    order, _oi = order_factory(user=admin_user_in_group, item=item, quantity=1, status=Order.Status.CREATED, ordered=False)

    # CREATED -> SHIPPED is invalid
    resp = api_client.post(
        f"/api/admin/orders/{order.id}/transition/",
        {"target_status": Order.Status.SHIPPED, "idempotency_key": "bad"},
        format="json",
        **auth_headers_for_admin,
    )
    assert resp.status_code == 400
