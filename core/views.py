"""Views for product browsing, cart operations, checkout, payments, and refunds.

This module intentionally keeps views thin by delegating business logic to core.services.*.
"""

from __future__ import annotations

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from .forms import CheckoutForm, CouponForm, PaymentForm, RefundForm
from .models import Item, Order, UserProfile
from .services.cart import (
    add_item_to_cart,
    remove_item_from_cart,
    remove_single_quantity_from_cart,
)
from .services.checkout import (
    apply_checkout_form_to_order,
    get_default_addresses_context,
)
from .services.coupons import get_coupon_by_code
from .services.payments import (
    StripeChargeParams,
    create_stripe_charge,
    ensure_stripe_customer_with_source,
    finalize_successful_order,
    list_customer_cards,
)
from .services.refunds import request_refund

stripe.api_key = settings.STRIPE_SECRET_KEY


class CheckoutView(LoginRequiredMixin, View):
    """Collect shipping/billing addresses and choose payment option.

    Endpoint: /checkout/
    """

    def get(self, *_args, **_kwargs):
        """Render checkout page with an active order and optional default addresses."""
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
        except ObjectDoesNotExist:
            messages.info(self.request, "You do not have an active order")
            return redirect("core:checkout")

        context = self._build_checkout_context(order=order)
        return render(self.request, "checkout.html", context)

    def post(self, *_args, **_kwargs):
        """Validate checkout form, persist addresses to the order, and redirect to payment selection."""
        form = CheckoutForm(self.request.POST or None)
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect("core:order-summary")

        if not form.is_valid():
            # Delegate input validation to the form. If invalid, keep existing behavior (warn + back).
            messages.warning(self.request, "Invalid data received")
            return redirect("core:checkout")

        address_result = apply_checkout_form_to_order(
            user=self.request.user, order=order, form=form
        )
        if address_result.error_message:
            messages.info(self.request, address_result.error_message)
            return redirect("core:checkout")

        payment_option = form.cleaned_data.get("payment_option")
        return self._redirect_to_payment(payment_option=payment_option)

    def _build_checkout_context(self, *, order: Order) -> dict:
        """Build template context for checkout page."""
        context = {
            "form": CheckoutForm(),
            "couponform": CouponForm(),
            "order": order,
            "DISPLAY_COUPON_FORM": True,
        }
        context.update(get_default_addresses_context(user=self.request.user))
        return context

    def _redirect_to_payment(self, *, payment_option: str):
        """Redirect to the chosen payment option page."""
        if payment_option == "S":
            return redirect("core:payment", payment_option="stripe")
        if payment_option == "P":
            return redirect("core:payment", payment_option="paypal")
        messages.warning(self.request, "Invalid payment option selected")
        return redirect("core:checkout")


class PaymentView(LoginRequiredMixin, View):
    """Handle Stripe payments for an active order.

    Endpoint: /payment/<payment_option>/
    """

    def get(self, *_args, **_kwargs):
        """Render the payment page if the order has a billing address."""
        order = Order.objects.get(user=self.request.user, ordered=False)
        if not order.billing_address:
            messages.warning(self.request, "You have not added a billing address")
            return redirect("core:checkout")

        context = self._build_payment_context(order=order)
        return render(self.request, "payment.html", context)

    def post(self, *_args, **_kwargs):
        """Charge via Stripe and finalize the order.

        Note: this keeps behavior consistent with the original code including redirects/messages.
        """
        order = Order.objects.get(user=self.request.user, ordered=False)
        form = PaymentForm(self.request.POST)
        userprofile = UserProfile.objects.get(user=self.request.user)

        if not form.is_valid():
            messages.warning(self.request, "Invalid data received")
            return redirect("/payment/stripe/")

        token = form.cleaned_data.get("stripeToken")
        save = form.cleaned_data.get("save")
        use_default = form.cleaned_data.get("use_default")

        # TODO: Consider adding rate limiting on payment submission.
        # TODO: Consider adding CSP nonces and moving inline JS from templates.

        try:
            charge_id = self._charge_order(
                order=order,
                userprofile=userprofile,
                token=token,
                save=save,
                use_default=use_default,
            )
            finalize_successful_order(
                order=order, user=self.request.user, charge_id=charge_id
            )
            messages.success(self.request, "Your order was successful!")
            return redirect("/")

        except stripe.error.CardError as e:
            body = e.json_body
            err = body.get("error", {})
            messages.warning(self.request, f"{err.get('message')}")
            return redirect("/")

        except stripe.error.RateLimitError:
            messages.warning(self.request, "Rate limit error")
            return redirect("/")

        except stripe.error.InvalidRequestError as e:
            # Invalid parameters were supplied to Stripe's API
            print(e)
            messages.warning(self.request, "Invalid parameters")
            return redirect("/")

        except stripe.error.AuthenticationError:
            messages.warning(self.request, "Not authenticated")
            return redirect("/")

        except stripe.error.APIConnectionError:
            messages.warning(self.request, "Network error")
            return redirect("/")

        except stripe.error.StripeError:
            messages.warning(
                self.request,
                "Something went wrong. You were not charged. Please try again.",
            )
            return redirect("/")

        except Exception:
            messages.warning(
                self.request,
                "A serious error occurred. We have been notifed.",
            )
            return redirect("/")

    def _build_payment_context(self, *, order: Order) -> dict:
        """Build template context for payment page, including stored card if available."""
        context = {
            "order": order,
            "DISPLAY_COUPON_FORM": False,
            "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY,
        }

        userprofile = self.request.user.userprofile
        if userprofile.one_click_purchasing and userprofile.stripe_customer_id:
            card_list = list_customer_cards(userprofile.stripe_customer_id, limit=3)
            if len(card_list) > 0:
                context.update({"card": card_list[0]})
        return context

    def _charge_order(
        self,
        *,
        order: Order,
        userprofile: UserProfile,
        token: str,
        save: bool,
        use_default: bool,
    ) -> str:
        """Charge the order total and return Stripe charge id."""
        amount_cents = int(order.get_total() * 100)

        customer_id = None
        source_token = None

        if save:
            # Save card requires a token to be present.
            if not token:
                raise stripe.error.InvalidRequestError(
                    message="Missing Stripe token", param="stripeToken"
                )
            customer_id = ensure_stripe_customer_with_source(
                user=self.request.user, userprofile=userprofile, token=token
            )

        if use_default or save:
            # Charging a customer because token cannot be charged more than once.
            customer_id = customer_id or userprofile.stripe_customer_id
        else:
            # One-time token charge.
            source_token = token

        charge = create_stripe_charge(
            params=StripeChargeParams(
                amount_cents=amount_cents,
                currency="usd",
                customer_id=customer_id,
                source_token=source_token,
            )
        )
        return charge["id"]


class HomeView(ListView):
    """Render the home page with a paginated list of items."""

    model = Item
    paginate_by = 10
    template_name = "home.html"


class OrderSummaryView(LoginRequiredMixin, View):
    """Show the active (un-ordered) cart summary page."""

    def get(self, *_args, **_kwargs):
        """Render order summary for the current user's active order."""
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            context = {"object": order}
            return render(self.request, "order_summary.html", context)
        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect("/")


class ItemDetailView(DetailView):
    """Product detail page."""

    model = Item
    template_name = "product.html"

    def get_queryset(self):
        """Optimize item detail query (avoid selecting unused fields)."""
        return Item.objects.only(
            "id",
            "title",
            "price",
            "discount_price",
            "category",
            "label",
            "slug",
            "description",
            "image",
        )


@login_required
def add_to_cart(request, slug):
    # PUBLIC_INTERFACE
    """Add an item to the user's cart (creates an order if none exists)."""
    item = get_object_or_404(Item, slug=slug)
    result = add_item_to_cart(user=request.user, item=item)
    messages.info(request, result.message)
    if result.redirect_kwargs:
        return redirect(result.redirect_name, **result.redirect_kwargs)
    return redirect(result.redirect_name)


@login_required
def remove_from_cart(request, slug):
    # PUBLIC_INTERFACE
    """Remove an item entirely from the user's cart."""
    item = get_object_or_404(Item, slug=slug)
    result = remove_item_from_cart(user=request.user, item=item)
    messages.info(request, result.message)
    if result.redirect_kwargs:
        return redirect(result.redirect_name, **result.redirect_kwargs)
    return redirect(result.redirect_name)


@login_required
def remove_single_item_from_cart(request, slug):
    # PUBLIC_INTERFACE
    """Remove a single quantity of an item from the cart (or remove it if qty hits 0)."""
    item = get_object_or_404(Item, slug=slug)
    result = remove_single_quantity_from_cart(user=request.user, item=item)
    messages.info(request, result.message)
    if result.redirect_kwargs:
        return redirect(result.redirect_name, **result.redirect_kwargs)
    return redirect(result.redirect_name)


class AddCouponView(LoginRequiredMixin, View):
    """Apply a coupon code to the active order."""

    def post(self, *_args, **_kwargs):
        """Validate coupon form and attach coupon to the current user's active order."""
        form = CouponForm(self.request.POST or None)
        if not form.is_valid():
            messages.info(self.request, "Invalid data received")
            return redirect("core:checkout")

        try:
            code = form.cleaned_data.get("code")
            order = Order.objects.get(user=self.request.user, ordered=False)
        except ObjectDoesNotExist:
            messages.info(self.request, "You do not have an active order")
            return redirect("core:checkout")

        coupon = get_coupon_by_code(code=code)
        if not coupon:
            messages.info(self.request, "This coupon does not exist")
            return redirect("core:checkout")

        order.coupon = coupon
        order.save()
        messages.success(self.request, "Successfully added coupon")
        return redirect("core:checkout")


class RequestRefundView(LoginRequiredMixin, View):
    """Allow user to request a refund by providing their order ref_code."""

    def get(self, *_args, **_kwargs):
        """Render the refund request form."""
        form = RefundForm()
        context = {"form": form}
        return render(self.request, "request_refund.html", context)

    def post(self, *_args, **_kwargs):
        """Validate refund request form and record a refund request."""
        form = RefundForm(self.request.POST)
        if not form.is_valid():
            messages.info(self.request, "Invalid data received")
            return redirect("core:request-refund")

        ref_code = form.cleaned_data.get("ref_code")
        message = form.cleaned_data.get("message")
        email = form.cleaned_data.get("email")

        result = request_refund(ref_code=ref_code, message=message, email=email)
        messages.info(self.request, result.message)
        return redirect("core:request-refund")
