"""
Payment service abstraction.

Goals:
- Hide provider-specific logic (Stripe vs dummy simulator) behind a single interface.
- Ensure idempotent handling of payment attempts (safe retries).
- Persist rich metadata in the Payment model for audit/troubleshooting.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.db import transaction

from core.models import Order, Payment


class PaymentResultCode(str, Enum):
    """High-level result codes consumed by UI/API callers."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REQUIRES_ACTION = "REQUIRES_ACTION"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True)
class PaymentAttemptResult:
    """
    Result returned by the payment service.

    payment: The Payment record created/updated for this attempt (if any).
    code: High-level outcome code.
    message: Human readable message (safe to show to user if desired).
    provider_reference: Provider payment intent/charge identifier.
    raw: Provider-specific raw payload/metadata (JSON-serializable).
    """

    payment: Optional[Payment]
    code: PaymentResultCode
    message: str
    provider_reference: Optional[str]
    raw: Dict[str, Any]


def _is_stripe_configured() -> bool:
    """
    Detect whether Stripe keys are configured.

    We intentionally default to dummy mode unless Stripe secret key is present.
    """
    secret = getattr(settings, "STRIPE_SECRET_KEY", None)
    return bool(secret)


def _get_mode() -> str:
    """
    Determine which payment mode to run in.

    Supported:
      - dummy
      - stripe

    Selection rules:
      1) If PAYMENT_MODE is set, use it (validated).
      2) Else if Stripe is configured, use stripe.
      3) Else default to dummy.
    """
    configured = getattr(settings, "PAYMENT_MODE", None) or os.environ.get("PAYMENT_MODE")
    if configured:
        configured = configured.strip().lower()
        if configured not in {"dummy", "stripe"}:
            return "dummy"
        if configured == "stripe" and not _is_stripe_configured():
            return "dummy"
        return configured
    return "stripe" if _is_stripe_configured() else "dummy"


def _dummy_outcome_settings() -> Tuple[str, float]:
    """
    Read dummy outcome settings from environment/settings.

    PAYMENT_DUMMY_OUTCOME:
      - success | fail | random
    PAYMENT_DUMMY_FAIL_RATE:
      - float in [0,1] used only when outcome == random
    """
    outcome = getattr(settings, "PAYMENT_DUMMY_OUTCOME", None) or os.environ.get("PAYMENT_DUMMY_OUTCOME", "success")
    outcome = str(outcome).strip().lower()
    if outcome not in {"success", "fail", "random"}:
        outcome = "success"

    fail_rate = getattr(settings, "PAYMENT_DUMMY_FAIL_RATE", None) or os.environ.get("PAYMENT_DUMMY_FAIL_RATE", "0.0")
    try:
        fail_rate_f = float(fail_rate)
    except Exception:
        fail_rate_f = 0.0
    fail_rate_f = max(0.0, min(1.0, fail_rate_f))
    return outcome, fail_rate_f


def _create_or_get_payment_for_idempotency(
    *,
    order: Order,
    user,
    idempotency_key: str,
    provider: str,
    mode: str,
    amount: float,
) -> Payment:
    """
    Create (or return existing) Payment record for an idempotency key.

    This ensures safe retries do not create duplicate Payment records.
    """
    with transaction.atomic():
        existing = Payment.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        payment = Payment.objects.create(
            user=user,
            amount=amount,
            provider=provider,
            mode=mode,
            idempotency_key=idempotency_key,
            status=Payment.Status.PENDING,
            raw_metadata={},
        )
        return payment


def _finalize_success(
    *,
    order: Order,
    payment: Payment,
    provider_reference: str,
    raw: Dict[str, Any],
) -> Payment:
    """Mark payment succeeded and attach to order (idempotent)."""
    with transaction.atomic():
        payment_db = Payment.objects.select_for_update().get(pk=payment.pk)
        # If already succeeded, treat as idempotent success.
        if payment_db.status != Payment.Status.SUCCEEDED:
            payment_db.status = Payment.Status.SUCCEEDED
            payment_db.provider_reference = provider_reference
            payment_db.error_message = ""
            payment_db.raw_metadata = raw or {}
            payment_db.save()

        order_db = Order.objects.select_for_update().get(pk=order.pk)
        if order_db.payment_id != payment_db.id:
            order_db.payment = payment_db
        # Keep legacy boolean and new status transition logic where caller currently does it.
        # We do not set order.ordered here to avoid mixing domain transitions in service.
        order_db.save()
        return payment_db


def _finalize_failure(
    *,
    payment: Payment,
    provider_reference: Optional[str],
    message: str,
    raw: Dict[str, Any],
) -> Payment:
    """Mark payment failed with message (idempotent)."""
    with transaction.atomic():
        payment_db = Payment.objects.select_for_update().get(pk=payment.pk)
        # Don't downgrade a succeeded payment.
        if payment_db.status != Payment.Status.SUCCEEDED:
            payment_db.status = Payment.Status.FAILED
            payment_db.provider_reference = provider_reference
            payment_db.error_message = message or ""
            payment_db.raw_metadata = raw or {}
            payment_db.save()
        return payment_db


def _stripe_charge(
    *,
    amount_cents: int,
    currency: str,
    token: Optional[str],
    customer_id: Optional[str],
    idempotency_key: str,
) -> Dict[str, Any]:
    """
    Execute Stripe charge with safe retries via Stripe idempotency key.

    Returns charge dict-like (from stripe python lib).
    """
    import stripe  # local import so dummy mode doesn't require Stripe initialization at import time

    stripe.api_key = settings.STRIPE_SECRET_KEY

    params: Dict[str, Any] = {
        "amount": amount_cents,
        "currency": currency,
    }
    if customer_id:
        params["customer"] = customer_id
    else:
        params["source"] = token

    # Stripe's python lib supports idempotency_key via request_options.
    # See: https://stripe.com/docs/api/idempotent_requests
    charge = stripe.Charge.create(params, idempotency_key=idempotency_key)
    return charge


# PUBLIC_INTERFACE
def get_payment_mode() -> str:
    """Return effective payment mode ('dummy' or 'stripe')."""
    return _get_mode()


# PUBLIC_INTERFACE
def attempt_payment_for_order(
    *,
    order: Order,
    user,
    amount: float,
    currency: str = "usd",
    idempotency_key: Optional[str] = None,
    stripe_token: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    dummy_force_outcome: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> PaymentAttemptResult:
    """
    Attempt a payment for an order using the configured provider.

    Parameters:
      order: Order being paid.
      user: Request user.
      amount: Amount in dollars (float) consistent with Order.get_total() usage.
      currency: 'usd' by default.
      idempotency_key: caller-supplied idempotency key; if omitted we generate one.
      stripe_token: Stripe token (one-time) for non-saved card charge.
      stripe_customer_id: Stripe customer id for saved card charge.
      dummy_force_outcome: For dummy mode API tests, can force 'success' or 'fail'.
      extra_metadata: Additional JSON metadata to persist to Payment.raw_metadata.

    Returns:
      PaymentAttemptResult with outcome code + Payment record.
    """
    mode = _get_mode()
    provider = "stripe" if mode == "stripe" else "dummy"

    if idempotency_key is None:
        idempotency_key = f"pay:{order.id}:{uuid.uuid4().hex}"

    payment = _create_or_get_payment_for_idempotency(
        order=order,
        user=user,
        idempotency_key=idempotency_key,
        provider=provider,
        mode=mode,
        amount=amount,
    )

    # If already succeeded, return idempotent success.
    if payment.status == Payment.Status.SUCCEEDED:
        return PaymentAttemptResult(
            payment=payment,
            code=PaymentResultCode.SUCCEEDED,
            message="Payment already succeeded.",
            provider_reference=payment.provider_reference,
            raw=payment.raw_metadata or {},
        )

    base_raw: Dict[str, Any] = {
        "order_id": order.id,
        "amount": amount,
        "currency": currency,
        "mode": mode,
        "provider": provider,
        "extra": extra_metadata or {},
    }

    try:
        if mode == "dummy":
            outcome_setting, fail_rate = _dummy_outcome_settings()
            forced = (dummy_force_outcome or "").strip().lower() if dummy_force_outcome else None
            if forced in {"success", "fail"}:
                outcome = forced
            elif outcome_setting == "random":
                import random as _random

                outcome = "fail" if _random.random() < fail_rate else "success"
            else:
                outcome = outcome_setting

            provider_reference = f"dummy_{uuid.uuid4().hex}"
            raw = {**base_raw, "dummy": {"outcome": outcome, "fail_rate": fail_rate}}

            if outcome == "success":
                payment = _finalize_success(order=order, payment=payment, provider_reference=provider_reference, raw=raw)
                return PaymentAttemptResult(
                    payment=payment,
                    code=PaymentResultCode.SUCCEEDED,
                    message="Dummy payment succeeded.",
                    provider_reference=provider_reference,
                    raw=raw,
                )

            payment = _finalize_failure(
                payment=payment,
                provider_reference=provider_reference,
                message="Dummy payment failed (simulated).",
                raw=raw,
            )
            return PaymentAttemptResult(
                payment=payment,
                code=PaymentResultCode.FAILED,
                message="Dummy payment failed (simulated).",
                provider_reference=provider_reference,
                raw=raw,
            )

        # Stripe mode
        if not _is_stripe_configured():
            payment = _finalize_failure(
                payment=payment,
                provider_reference=None,
                message="Stripe is not configured.",
                raw=base_raw,
            )
            return PaymentAttemptResult(
                payment=payment,
                code=PaymentResultCode.INVALID_REQUEST,
                message="Stripe is not configured.",
                provider_reference=None,
                raw=base_raw,
            )

        if not stripe_customer_id and not stripe_token:
            payment = _finalize_failure(
                payment=payment,
                provider_reference=None,
                message="Missing payment source (stripeToken or customer id).",
                raw=base_raw,
            )
            return PaymentAttemptResult(
                payment=payment,
                code=PaymentResultCode.INVALID_REQUEST,
                message="Missing payment source.",
                provider_reference=None,
                raw=base_raw,
            )

        amount_cents = int(amount * 100)
        charge = _stripe_charge(
            amount_cents=amount_cents,
            currency=currency,
            token=stripe_token,
            customer_id=stripe_customer_id,
            idempotency_key=idempotency_key,
        )

        provider_reference = charge.get("id")
        raw = {**base_raw, "stripe": {"charge": dict(charge)}}
        payment = _finalize_success(order=order, payment=payment, provider_reference=provider_reference, raw=raw)

        return PaymentAttemptResult(
            payment=payment,
            code=PaymentResultCode.SUCCEEDED,
            message="Payment succeeded.",
            provider_reference=provider_reference,
            raw=raw,
        )

    except Exception as e:
        # Catch-all; Stripe-specific exceptions are handled by caller in legacy flow,
        # but we want service to be robust and structured.
        raw = {**base_raw, "exception": {"type": e.__class__.__name__, "message": str(e)}}
        payment = _finalize_failure(
            payment=payment,
            provider_reference=payment.provider_reference,
            message=str(e),
            raw=raw,
        )
        return PaymentAttemptResult(
            payment=payment,
            code=PaymentResultCode.PROVIDER_ERROR,
            message="Payment provider error.",
            provider_reference=payment.provider_reference,
            raw=raw,
        )
