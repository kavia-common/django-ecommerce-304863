"""Coupon related business logic."""

from __future__ import annotations

from typing import Optional

from core.models import Coupon


# PUBLIC_INTERFACE
def get_coupon_by_code(*, code: str) -> Optional[Coupon]:
    """Return coupon for a code, or None if not found."""
    try:
        return Coupon.objects.get(code=code)
    except Coupon.DoesNotExist:
        return None
