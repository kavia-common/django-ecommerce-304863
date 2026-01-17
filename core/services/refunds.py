"""Refund related business logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.models import Order, Refund


@dataclass(frozen=True)
class RefundRequestResult:
    """Result of requesting a refund by ref_code."""

    success: bool
    message: str
    order: Optional[Order] = None


# PUBLIC_INTERFACE
def request_refund(*, ref_code: str, message: str, email: str) -> RefundRequestResult:
    """Record a refund request for an order.

    This preserves existing behavior:
    - Finds order by ref_code
    - Marks refund_requested
    - Creates Refund row with reason/email
    """
    try:
        order = Order.objects.get(ref_code=ref_code)
    except Order.DoesNotExist:
        return RefundRequestResult(success=False, message="This order does not exist.", order=None)

    order.refund_requested = True
    order.save()

    refund = Refund(order=order, reason=message, email=email)
    refund.save()

    # TODO: initiate provider refund (e.g., Stripe Refund API) once business rules are defined.
    return RefundRequestResult(success=True, message="Your request was received.", order=order)
