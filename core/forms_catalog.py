"""Catalog (product listing) form.

This is separated from checkout/payment forms to keep responsibilities clear.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms

from .models import CATEGORY_CHOICES


class CatalogFilterForm(forms.Form):
    """Catalog query parameters for search/filter/sort on the product listing."""

    SORT_CHOICES = (
        ("relevance", "Relevance"),
        ("price_asc", "Price: Low → High"),
        ("price_desc", "Price: High → Low"),
        ("title_asc", "Name: A → Z"),
        ("title_desc", "Name: Z → A"),
    )

    q = forms.CharField(required=False, max_length=100)
    category = forms.ChoiceField(
        required=False,
        choices=(("", "All categories"),) + tuple(CATEGORY_CHOICES),
    )
    price_min = forms.CharField(required=False, max_length=20)
    price_max = forms.CharField(required=False, max_length=20)
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def clean_price_min(self) -> Decimal | None:
        """Validate min price as a non-negative decimal (optional)."""
        raw = (self.cleaned_data.get("price_min") or "").strip()
        if not raw:
            return None
        try:
            val = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise forms.ValidationError("Enter a valid minimum price.") from exc
        if val < 0:
            raise forms.ValidationError("Minimum price cannot be negative.")
        return val

    def clean_price_max(self) -> Decimal | None:
        """Validate max price as a non-negative decimal (optional)."""
        raw = (self.cleaned_data.get("price_max") or "").strip()
        if not raw:
            return None
        try:
            val = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise forms.ValidationError("Enter a valid maximum price.") from exc
        if val < 0:
            raise forms.ValidationError("Maximum price cannot be negative.")
        return val

    def clean(self):
        """Ensure min <= max when both are provided."""
        cleaned = super().clean()
        price_min = cleaned.get("price_min")
        price_max = cleaned.get("price_max")
        if price_min is not None and price_max is not None and price_min > price_max:
            self.add_error("price_max", "Maximum price must be greater than minimum price.")
        return cleaned
