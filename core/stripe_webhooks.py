import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Order, Payment


def _webhook_secret() -> str:
    """Return configured Stripe webhook secret (may be empty)."""
    return getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""


# PUBLIC_INTERFACE
@csrf_exempt
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """Stripe webhook endpoint for asynchronous payment updates.

    - Verifies Stripe signature if STRIPE_WEBHOOK_SECRET is set.
    - Falls back to unsigned parsing if STRIPE_WEBHOOK_SECRET is absent (dev-friendly).
    - Idempotent processing: stores Stripe event id in Payment.stripe_event_id (unique).
    - Finalizes order only on payment_intent.succeeded.

    Stripe should be configured to send at least:
      - payment_intent.succeeded
      - payment_intent.payment_failed (optional)

    Returns:
        200 OK for successfully processed (or already processed) events,
        400 for invalid payload or invalid signature.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = _webhook_secret()

    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
        else:
            # Safe fallback when secret isn't configured.
            event = stripe.Event.construct_from(request.json if hasattr(request, "json") else {}, stripe.api_key)
            # If request.json isn't available, parse manually.
            if not getattr(event, "id", None):
                import json as _json

                event = stripe.Event.construct_from(_json.loads(payload.decode("utf-8")), stripe.api_key)
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    event_id = event.get("id")
    event_type = event.get("type")

    # We only process a small set of event types.
    if event_type not in {"payment_intent.succeeded", "payment_intent.payment_failed"}:
        return HttpResponse(status=200)

    # Idempotency: if we've processed this event, return 200.
    if event_id and Payment.objects.filter(stripe_event_id=event_id).exists():
        return HttpResponse(status=200)

    if event_type == "payment_intent.succeeded":
        pi = event["data"]["object"]
        order_id = pi.get("metadata", {}).get("order_id")
        if not order_id:
            # No order reference; nothing to do.
            return HttpResponse(status=200)

        # Finalize only if the order is still an unpaid cart; webhook can be retried safely.
        try:
            order = Order.objects.select_related("payment").get(pk=int(order_id))
        except Exception:
            return HttpResponse(status=200)

        if order.ordered:
            # Already finalized; but still record event for idempotency.
            Payment.objects.create(
                stripe_event_id=event_id,
                stripe_payment_intent_id=pi.get("id"),
                stripe_payment_intent_client_secret=pi.get("client_secret"),
                user=order.user,
                amount=order.get_total(),
            )
            return HttpResponse(status=200)

        # Create Payment + finalize order atomically. Unique event id ensures idempotency.
        with transaction.atomic():
            payment = Payment.objects.create(
                stripe_event_id=event_id,
                stripe_payment_intent_id=pi.get("id"),
                stripe_payment_intent_client_secret=pi.get("client_secret"),
                user=order.user,
                amount=order.get_total(),
            )

            # Decrement stock and mark order paid (mirrors synchronous finalize logic).
            from .views import _finalize_order_after_successful_payment  # local import to avoid circular

            _finalize_order_after_successful_payment(order=order, user=order.user, payment=payment)

        return HttpResponse(status=200)

    # payment_intent.payment_failed: record event for idempotency (optional)
    if event_type == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        Payment.objects.create(
            stripe_event_id=event_id,
            stripe_payment_intent_id=pi.get("id"),
            stripe_payment_intent_client_secret=pi.get("client_secret"),
            user=None,
            amount=0.0,
        )
        return HttpResponse(status=200)

    return HttpResponse(status=200)
