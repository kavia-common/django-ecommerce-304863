"""Form definitions for checkout, payments, coupons, and refunds.

This module centralizes input validation rules so that views/services do not need
ad-hoc non-empty checks. The public form classes and field names are kept stable
to avoid breaking existing views/templates.
"""

from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinLengthValidator, RegexValidator
from django_countries.fields import CountryField
from django_countries.widgets import CountrySelectWidget

PAYMENT_CHOICES = (
    ("S", "Stripe"),
    ("P", "PayPal"),
)

# Common error messages (kept consistent across forms/templates).
_REQUIRED_MSG = "This field is required."
_INVALID_CHOICE_MSG = "Select a valid choice."


def _is_blank(value: object) -> bool:
    """Return True when value is None or an empty/whitespace-only string."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


class CheckoutForm(forms.Form):
    """Collect shipping/billing address details and payment option during checkout.

    Contextual required rules:
    - If use_default_shipping is False, require shipping fields.
    - If same_billing_address is False AND use_default_billing is False, require billing fields.
    - If same_billing_address is True, billing address fields are not required/used.
    """

    shipping_address = forms.CharField(
        required=False,
        validators=[MaxLengthValidator(100)],
        error_messages={"required": _REQUIRED_MSG},
    )
    shipping_address2 = forms.CharField(
        required=False,
        validators=[MaxLengthValidator(100)],
    )
    shipping_country = CountryField(blank_label="(select country)").formfield(
        required=False,
        widget=CountrySelectWidget(
            attrs={
                "class": "custom-select d-block w-100",
            }
        ),
        error_messages={"required": _REQUIRED_MSG},
    )
    shipping_zip = forms.CharField(
        required=False,
        validators=[
            MaxLengthValidator(20),
            # Keep permissive to support many regions while still rejecting obviously bad input.
            RegexValidator(
                regex=r"^[0-9A-Za-z \-]{3,20}$",
                message="Enter a valid ZIP / postal code.",
            ),
        ],
        error_messages={"required": _REQUIRED_MSG},
    )

    billing_address = forms.CharField(
        required=False,
        validators=[MaxLengthValidator(100)],
        error_messages={"required": _REQUIRED_MSG},
    )
    billing_address2 = forms.CharField(
        required=False,
        validators=[MaxLengthValidator(100)],
    )
    billing_country = CountryField(blank_label="(select country)").formfield(
        required=False,
        widget=CountrySelectWidget(
            attrs={
                "class": "custom-select d-block w-100",
            }
        ),
        error_messages={"required": _REQUIRED_MSG},
    )
    billing_zip = forms.CharField(
        required=False,
        validators=[
            MaxLengthValidator(20),
            RegexValidator(
                regex=r"^[0-9A-Za-z \-]{3,20}$",
                message="Enter a valid ZIP / postal code.",
            ),
        ],
        error_messages={"required": _REQUIRED_MSG},
    )

    same_billing_address = forms.BooleanField(required=False)
    set_default_shipping = forms.BooleanField(required=False)
    use_default_shipping = forms.BooleanField(required=False)
    set_default_billing = forms.BooleanField(required=False)
    use_default_billing = forms.BooleanField(required=False)

    payment_option = forms.ChoiceField(
        widget=forms.RadioSelect,
        choices=PAYMENT_CHOICES,
        error_messages={"required": _REQUIRED_MSG, "invalid_choice": _INVALID_CHOICE_MSG},
    )

    def clean(self):
        """Validate contextual requirements for addresses based on checkbox selections."""
        cleaned_data = super().clean()

        use_default_shipping = bool(cleaned_data.get("use_default_shipping"))
        use_default_billing = bool(cleaned_data.get("use_default_billing"))
        same_billing_address = bool(cleaned_data.get("same_billing_address"))

        # Shipping address required when not using default shipping.
        if not use_default_shipping:
            self._require_shipping_fields(cleaned_data)

        # Billing address required when NOT using same_billing_address and not using default billing.
        if not same_billing_address and not use_default_billing:
            self._require_billing_fields(cleaned_data)

        # If same_billing_address is checked, billing fields are ignored; no extra validation needed.
        return cleaned_data

    def _require_shipping_fields(self, cleaned_data: dict) -> None:
        """Add per-field errors for required shipping fields."""
        if _is_blank(cleaned_data.get("shipping_address")):
            self.add_error("shipping_address", _REQUIRED_MSG)
        if _is_blank(cleaned_data.get("shipping_country")):
            self.add_error("shipping_country", _REQUIRED_MSG)
        if _is_blank(cleaned_data.get("shipping_zip")):
            self.add_error("shipping_zip", _REQUIRED_MSG)

    def _require_billing_fields(self, cleaned_data: dict) -> None:
        """Add per-field errors for required billing fields."""
        if _is_blank(cleaned_data.get("billing_address")):
            self.add_error("billing_address", _REQUIRED_MSG)
        if _is_blank(cleaned_data.get("billing_country")):
            self.add_error("billing_country", _REQUIRED_MSG)
        if _is_blank(cleaned_data.get("billing_zip")):
            self.add_error("billing_zip", _REQUIRED_MSG)


class CouponForm(forms.Form):
    """Collect a promo/coupon code."""

    code = forms.CharField(
        validators=[
            MinLengthValidator(3),
            MaxLengthValidator(15),
            RegexValidator(
                # Coupons are commonly alnum + -/_; keep strict enough to catch junk.
                regex=r"^[A-Za-z0-9][A-Za-z0-9\-_]*$",
                message="Enter a valid coupon code.",
            ),
        ],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Promo code",
                "aria-label": "Recipient's username",
                "aria-describedby": "basic-addon2",
            }
        ),
        error_messages={"required": _REQUIRED_MSG},
    )

    def clean_code(self) -> str:
        """Normalize coupon code input (strip/uppercase) and validate format."""
        value = (self.cleaned_data.get("code") or "").strip()
        if not value:
            raise ValidationError(_REQUIRED_MSG)

        # Normalize to uppercase for consistent comparisons/storage.
        value = value.upper()

        # Re-validate after normalization (defensive; field validators already run).
        if not re.match(r"^[A-Z0-9][A-Z0-9\-_]*$", value):
            raise ValidationError("Enter a valid coupon code.")
        return value


class RefundForm(forms.Form):
    """Collect refund request details."""

    ref_code = forms.CharField(
        validators=[
            MinLengthValidator(4),
            MaxLengthValidator(20),
            RegexValidator(
                # Keep compatible with typical Order.ref_code usage (usually alnum).
                regex=r"^[A-Za-z0-9]+$",
                message="Enter a valid reference code.",
            ),
        ],
        error_messages={"required": _REQUIRED_MSG},
    )
    message = forms.CharField(
        validators=[
            MinLengthValidator(10),
            MaxLengthValidator(2000),
        ],
        widget=forms.Textarea(
            attrs={
                "rows": 4,
            }
        ),
        error_messages={"required": _REQUIRED_MSG},
    )
    email = forms.EmailField(error_messages={"required": _REQUIRED_MSG})

    def clean_ref_code(self) -> str:
        """Normalize the reference code (strip/uppercase) and validate format."""
        value = (self.cleaned_data.get("ref_code") or "").strip()
        if not value:
            raise ValidationError(_REQUIRED_MSG)
        value = value.upper()
        if not re.match(r"^[A-Z0-9]+$", value):
            raise ValidationError("Enter a valid reference code.")
        return value


class PaymentForm(forms.Form):
    """Collect Stripe token and payment preferences."""

    stripeToken = forms.CharField(required=False)
    save = forms.BooleanField(required=False)
    use_default = forms.BooleanField(required=False)

    def clean(self):
        """Ensure the required Stripe token is present when needed."""
        cleaned_data = super().clean()

        token = cleaned_data.get("stripeToken")
        save = bool(cleaned_data.get("save"))
        use_default = bool(cleaned_data.get("use_default"))

        # If not using a default payment method, we need a token from Stripe.js checkout.
        # If saving, we also need a token to attach the source to the customer.
        if (not use_default or save) and _is_blank(token):
            self.add_error("stripeToken", "Payment token is required.")
        return cleaned_data
