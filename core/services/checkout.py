"""Checkout business logic: address selection/creation and order updates."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model

from core.models import Address, Order


@dataclass(frozen=True)
class AddressSelectionResult:
    """Result of attempting to resolve/set addresses for an order."""

    order: Order
    shipping_address: Address | None
    billing_address: Address | None
    error_message: str | None = None


def _is_valid_form(values) -> bool:
    """Internal helper matching the old is_valid_form() behavior."""
    return all(field != "" for field in values)


def _get_default_address(
    *, user: get_user_model(), address_type: str
) -> Address | None:
    qs = Address.objects.filter(user=user, address_type=address_type, default=True)
    return qs[0] if qs.exists() else None


def _create_address_from_form(
    *,
    user: get_user_model(),
    address_type: str,
    street_address: str,
    apartment_address: str,
    country,
    zip_code: str,
    set_default: bool,
) -> Address:
    address = Address(
        user=user,
        street_address=street_address,
        apartment_address=apartment_address,
        country=country,
        zip=zip_code,
        address_type=address_type,
    )
    address.save()

    if set_default:
        address.default = True
        address.save()

    return address


# PUBLIC_INTERFACE
def apply_checkout_form_to_order(
    *, user: get_user_model(), order: Order, form
) -> AddressSelectionResult:
    """Apply validated CheckoutForm data to the given order.

    This mirrors the original CheckoutView.post behavior but without view concerns.
    It does not redirect; it returns either addresses or an error message.
    """
    shipping_address: Address | None = None
    billing_address: Address | None = None

    use_default_shipping = form.cleaned_data.get("use_default_shipping")
    if use_default_shipping:
        shipping_address = _get_default_address(user=user, address_type="S")
        if not shipping_address:
            return AddressSelectionResult(
                order=order,
                shipping_address=None,
                billing_address=None,
                error_message="No default shipping address available",
            )
        order.shipping_address = shipping_address
        order.save()
    else:
        shipping_address1 = form.cleaned_data.get("shipping_address")
        shipping_address2 = form.cleaned_data.get("shipping_address2")
        shipping_country = form.cleaned_data.get("shipping_country")
        shipping_zip = form.cleaned_data.get("shipping_zip")

        if _is_valid_form([shipping_address1, shipping_country, shipping_zip]):
            shipping_address = _create_address_from_form(
                user=user,
                address_type="S",
                street_address=shipping_address1,
                apartment_address=shipping_address2,
                country=shipping_country,
                zip_code=shipping_zip,
                set_default=form.cleaned_data.get("set_default_shipping"),
            )
            order.shipping_address = shipping_address
            order.save()
        else:
            return AddressSelectionResult(
                order=order,
                shipping_address=None,
                billing_address=None,
                error_message="Please fill in the required shipping address fields",
            )

    use_default_billing = form.cleaned_data.get("use_default_billing")
    same_billing_address = form.cleaned_data.get("same_billing_address")

    if same_billing_address:
        # Duplicate shipping address as billing.
        billing_address = shipping_address
        billing_address.pk = None
        billing_address.save()
        billing_address.address_type = "B"
        billing_address.save()

        order.billing_address = billing_address
        order.save()

    elif use_default_billing:
        billing_address = _get_default_address(user=user, address_type="B")
        if not billing_address:
            return AddressSelectionResult(
                order=order,
                shipping_address=shipping_address,
                billing_address=None,
                error_message="No default billing address available",
            )
        order.billing_address = billing_address
        order.save()

    else:
        billing_address1 = form.cleaned_data.get("billing_address")
        billing_address2 = form.cleaned_data.get("billing_address2")
        billing_country = form.cleaned_data.get("billing_country")
        billing_zip = form.cleaned_data.get("billing_zip")

        if _is_valid_form([billing_address1, billing_country, billing_zip]):
            billing_address = _create_address_from_form(
                user=user,
                address_type="B",
                street_address=billing_address1,
                apartment_address=billing_address2,
                country=billing_country,
                zip_code=billing_zip,
                set_default=form.cleaned_data.get("set_default_billing"),
            )
            order.billing_address = billing_address
            order.save()
        else:
            return AddressSelectionResult(
                order=order,
                shipping_address=shipping_address,
                billing_address=None,
                error_message="Please fill in the required billing address fields",
            )

    return AddressSelectionResult(
        order=order,
        shipping_address=shipping_address,
        billing_address=billing_address,
        error_message=None,
    )


# PUBLIC_INTERFACE
def get_default_addresses_context(*, user: get_user_model()) -> dict:
    """Return context keys for default shipping/billing addresses (if present)."""
    context: dict = {}
    shipping = _get_default_address(user=user, address_type="S")
    if shipping:
        context["default_shipping_address"] = shipping
    billing = _get_default_address(user=user, address_type="B")
    if billing:
        context["default_billing_address"] = billing
    return context
