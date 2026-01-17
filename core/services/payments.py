"""Payment and Stripe integration helpers."""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Optional

import stripe
from django.contrib.auth import get_user_model

from core.models import Order, Payment, UserProfile


@dataclass(frozen=True)
class StripeChargeParams:
    """Parameters used to create a Stripe charge."""

    amount_cents: int
    currency: str = "usd"
    customer_id: Optional[str] = None
    source_token: Optional[str] = None


# PUBLIC_INTERFACE
def create_ref_code(*, length: int = 20) -> str:
    """Create a random ref code for an order."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# PUBLIC_INTERFACE
def ensure_stripe_customer_with_source(
    *,
    user: get_user_model(),
    userprofile: UserProfile,
    token: str,
) -> str:
    """Ensure the user has a Stripe customer and attach the card source.

    Returns the stripe_customer_id to be used for subsequent charges.
    """
    if userprofile.stripe_customer_id:
        customer = stripe.Customer.retrieve(userprofile.stripe_customer_id)
        customer.sources.create(source=token)
        return userprofile.stripe_customer_id

    customer = stripe.Customer.create(email=user.email)
    customer.sources.create(source=token)

    userprofile.stripe_customer_id = customer["id"]
    userprofile.one_click_purchasing = True
    userprofile.save()
    return customer["id"]


# PUBLIC_INTERFACE
def create_stripe_charge(*, params: StripeChargeParams) -> dict:
    """Create a Stripe charge and return the Stripe response dict.

    Note: Higher-level error handling (StripeError mapping) is expected in the view.
    """
    payload = {
        "amount": params.amount_cents,
        "currency": params.currency,
    }
    if params.customer_id:
        payload["customer"] = params.customer_id
    if params.source_token and not params.customer_id:
        payload["source"] = params.source_token

    return stripe.Charge.create(**payload)


# PUBLIC_INTERFACE
def finalize_successful_order(*, order: Order, user: get_user_model(), charge_id: str) -> Payment:
    """Create a Payment object and mark the order/items as ordered.

    Mirrors the original PaymentView.post behavior.
    """
    payment = Payment()
    payment.stripe_charge_id = charge_id
    payment.user = user
    payment.amount = order.get_total()
    payment.save()

    order_items = order.items.all()
    order_items.update(ordered=True)
    for item in order_items:
        item.save()

    order.ordered = True
    order.payment = payment
    order.ref_code = create_ref_code()
    order.save()

    return payment


# PUBLIC_INTERFACE
def list_customer_cards(*, stripe_customer_id: str, limit: int = 3) -> list[dict]:
    """List stored cards for a Stripe customer id."""
    cards = stripe.Customer.list_sources(
        stripe_customer_id,
        limit=limit,
        object="card",
    )
    return cards["data"]
