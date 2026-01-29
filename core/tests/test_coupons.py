import pytest

from core.models import Order


@pytest.mark.django_db
def test_admin_coupon_crud(api_client, auth_headers_for_admin):
    # Create
    create = api_client.post("/api/admin/coupons/", {"code": "SAVE5", "amount": 5.0}, format="json", **auth_headers_for_admin)
    assert create.status_code == 201
    coupon_id = create.json()["id"]

    # List
    listing = api_client.get("/api/admin/coupons/", **auth_headers_for_admin)
    assert listing.status_code == 200
    assert any(c["id"] == coupon_id for c in listing.json())

    # Detail
    detail = api_client.get(f"/api/admin/coupons/{coupon_id}/", **auth_headers_for_admin)
    assert detail.status_code == 200
    assert detail.json()["code"] == "SAVE5"

    # Patch
    patch = api_client.patch(f"/api/admin/coupons/{coupon_id}/", {"amount": 7.0}, format="json", **auth_headers_for_admin)
    assert patch.status_code == 200
    assert patch.json()["amount"] == 7.0

    # Delete
    delete = api_client.delete(f"/api/admin/coupons/{coupon_id}/", **auth_headers_for_admin)
    assert delete.status_code == 204


@pytest.mark.django_db
def test_coupon_apply_to_order_is_idempotent(coupon_factory, item_factory, order_factory, user):
    coupon = coupon_factory(code="IDEM", amount=3.0)
    item = item_factory(price=10.0)
    order, _oi = order_factory(user=user, item=item, quantity=1, status=Order.Status.CREATED, ordered=False)

    ok1, msg1, red1 = coupon.apply_to_order(user=user, order=order, idempotency_key="k1")
    assert ok1 is True
    assert red1 is None
    order.refresh_from_db()
    assert order.coupon_id == coupon.id

    ok2, msg2, red2 = coupon.apply_to_order(user=user, order=order, idempotency_key="k1")
    assert ok2 is True
    assert red2 is None
    order.refresh_from_db()
    assert order.coupon_id == coupon.id


@pytest.mark.django_db
def test_template_add_coupon_view_applies_coupon(django_client, coupon_factory, item_factory, order_factory, user):
    user.set_password("pw")
    user.save()
    assert django_client.login(username=user.username, password="pw") is True

    item = item_factory(price=20.0)
    order, _oi = order_factory(user=user, item=item, quantity=1, ordered=False)
    coupon = coupon_factory(code="TeSt", amount=5.0)

    resp = django_client.post("/add-coupon/", {"code": "test"})  # case-insensitive lookup
    # The view redirects back to checkout; we only assert it doesn't error.
    assert resp.status_code in (302, 200)

    order.refresh_from_db()
    assert order.coupon_id == coupon.id
    assert order.get_total() == 15.0
