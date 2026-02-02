import json
import random
import string

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, ListView, View
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .forms import CheckoutForm, CouponForm, RefundForm, PaymentForm
from .models import (
    Item,
    OrderItem,
    Order,
    Address,
    Payment,
    Coupon,
    Refund,
    UserProfile,
    Review,
    user_has_purchased_item,
)
from .rbac import request_is_admin

stripe.api_key = settings.STRIPE_SECRET_KEY


def _stripe_webhook_secret() -> str:
    """Return Stripe webhook secret if configured; empty string otherwise."""
    return getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""


def _finalize_order_after_successful_payment(*, order: Order, user, payment: Payment) -> None:
    """Finalize an order after Stripe confirms payment.

    This is shared between synchronous (client-confirmed PaymentIntent) and webhook flow.
    """
    # Only after Stripe confirms payment do we reserve/decrement stock.
    # Use a DB transaction + row locking to prevent oversell.
    with transaction.atomic():
        Item.atomic_decrement_stock_for_order(order)

        # assign the payment to the order
        order_items = order.items.all()
        order_items.update(ordered=True)
        for item in order_items:
            item.save()

        order.ordered = True
        order.payment = payment
        order.ref_code = create_ref_code()

        # New lifecycle: mark as placed on successful payment.
        # Keep legacy flags synced via Order.save().
        try:
            order.transition_to(Order.OrderStatus.PLACED, actor=user)
        except Exception:
            # Defensive: do not break checkout if an unexpected lifecycle issue occurs.
            pass

        order.save()

        # Record coupon redemption only AFTER order is paid.
        try:
            order.record_coupon_redemption_if_needed()
        except Exception:
            # Never block payment finalization due to coupon accounting.
            pass


def create_ref_code():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=20))


def products(request):
    context = {"items": Item.objects.all()}
    return render(request, "products.html", context)


def is_valid_form(values):
    valid = True
    for field in values:
        if field == "":
            valid = False
    return valid


class CheckoutView(View):
    def get(self, *args, **kwargs):
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)

            # Validate cart quantities against current stock before checkout.
            for oi in order.items.select_related("item").all():
                try:
                    oi.item.ensure_can_fulfill(oi.quantity)
                except ValueError as e:
                    messages.warning(self.request, str(e))
                    return redirect("core:order-summary")

            form = CheckoutForm()
            context = {
                "form": form,
                "couponform": CouponForm(),
                "order": order,
                "DISPLAY_COUPON_FORM": True,
            }

            shipping_address_qs = Address.objects.filter(
                user=self.request.user,
                address_type="S",
                default=True,
            )
            if shipping_address_qs.exists():
                context.update({"default_shipping_address": shipping_address_qs[0]})

            billing_address_qs = Address.objects.filter(
                user=self.request.user,
                address_type="B",
                default=True,
            )
            if billing_address_qs.exists():
                context.update({"default_billing_address": billing_address_qs[0]})
            return render(self.request, "checkout.html", context)
        except ObjectDoesNotExist:
            messages.info(self.request, "You do not have an active order")
            return redirect("core:checkout")

    def post(self, *args, **kwargs):
        form = CheckoutForm(self.request.POST or None)
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)

            # Re-validate cart quantities against current stock before accepting addresses.
            for oi in order.items.select_related("item").all():
                try:
                    oi.item.ensure_can_fulfill(oi.quantity)
                except ValueError as e:
                    messages.warning(self.request, str(e))
                    return redirect("core:order-summary")

            if form.is_valid():
                use_default_shipping = form.cleaned_data.get("use_default_shipping")
                if use_default_shipping:
                    address_qs = Address.objects.filter(
                        user=self.request.user,
                        address_type="S",
                        default=True,
                    )
                    if address_qs.exists():
                        shipping_address = address_qs[0]
                        order.shipping_address = shipping_address
                        order.save()
                    else:
                        messages.info(self.request, "No default shipping address available")
                        return redirect("core:checkout")
                else:
                    shipping_address1 = form.cleaned_data.get("shipping_address")
                    shipping_address2 = form.cleaned_data.get("shipping_address2")
                    shipping_country = form.cleaned_data.get("shipping_country")
                    shipping_zip = form.cleaned_data.get("shipping_zip")

                    if is_valid_form([shipping_address1, shipping_country, shipping_zip]):
                        shipping_address = Address(
                            user=self.request.user,
                            street_address=shipping_address1,
                            apartment_address=shipping_address2,
                            country=shipping_country,
                            zip=shipping_zip,
                            address_type="S",
                        )
                        shipping_address.save()

                        order.shipping_address = shipping_address
                        order.save()

                        set_default_shipping = form.cleaned_data.get("set_default_shipping")
                        if set_default_shipping:
                            shipping_address.default = True
                            shipping_address.save()
                    else:
                        messages.info(self.request, "Please fill in the required shipping address fields")

                use_default_billing = form.cleaned_data.get("use_default_billing")
                same_billing_address = form.cleaned_data.get("same_billing_address")

                if same_billing_address:
                    billing_address = shipping_address
                    billing_address.pk = None
                    billing_address.save()
                    billing_address.address_type = "B"
                    billing_address.save()
                    order.billing_address = billing_address
                    order.save()

                elif use_default_billing:
                    address_qs = Address.objects.filter(
                        user=self.request.user,
                        address_type="B",
                        default=True,
                    )
                    if address_qs.exists():
                        billing_address = address_qs[0]
                        order.billing_address = billing_address
                        order.save()
                    else:
                        messages.info(self.request, "No default billing address available")
                        return redirect("core:checkout")
                else:
                    billing_address1 = form.cleaned_data.get("billing_address")
                    billing_address2 = form.cleaned_data.get("billing_address2")
                    billing_country = form.cleaned_data.get("billing_country")
                    billing_zip = form.cleaned_data.get("billing_zip")

                    if is_valid_form([billing_address1, billing_country, billing_zip]):
                        billing_address = Address(
                            user=self.request.user,
                            street_address=billing_address1,
                            apartment_address=billing_address2,
                            country=billing_country,
                            zip=billing_zip,
                            address_type="B",
                        )
                        billing_address.save()

                        order.billing_address = billing_address
                        order.save()

                        set_default_billing = form.cleaned_data.get("set_default_billing")
                        if set_default_billing:
                            billing_address.default = True
                            billing_address.save()
                    else:
                        messages.info(self.request, "Please fill in the required billing address fields")

                payment_option = form.cleaned_data.get("payment_option")

                if payment_option == "S":
                    return redirect("core:payment", payment_option="stripe")
                if payment_option == "P":
                    return redirect("core:payment", payment_option="paypal")

                messages.warning(self.request, "Invalid payment option selected")
                return redirect("core:checkout")
        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect("core:order-summary")


class PaymentView(View):
    def get(self, *args, **kwargs):
        order = Order.objects.get(user=self.request.user, ordered=False)

        # Validate cart quantities against current stock before showing payment.
        for oi in order.items.select_related("item").all():
            try:
                oi.item.ensure_can_fulfill(oi.quantity)
            except ValueError as e:
                messages.warning(self.request, str(e))
                return redirect("core:order-summary")

        if not order.billing_address:
            messages.warning(self.request, "You have not added a billing address")
            return redirect("core:checkout")

        # Create/refresh a PaymentIntent so checkout uses PaymentIntents in test mode.
        # We do not mark the order as paid here; that happens only after confirmation.
        amount_cents = int(order.get_total() * 100)
        payment_intent = None

        try:
            # Idempotency prevents duplicate PaymentIntents on refresh.
            payment_intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                automatic_payment_methods={"enabled": True},
                metadata={
                    "order_id": str(order.id),
                    "user_id": str(self.request.user.id),
                },
                idempotency_key=f"order_{order.id}_pi_create",
            )
        except Exception:
            # Safe fallback: if PaymentIntent creation fails, we still render page and allow legacy token->Charge post.
            payment_intent = None

        context = {
            "order": order,
            "DISPLAY_COUPON_FORM": False,
            "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY,
            "stripe_payment_intent_client_secret": (payment_intent["client_secret"] if payment_intent else ""),
        }

        userprofile = self.request.user.userprofile
        if userprofile.one_click_purchasing:
            # fetch the users card list
            cards = stripe.Customer.list_sources(
                userprofile.stripe_customer_id,
                limit=3,
                object="card",
            )
            card_list = cards["data"]
            if len(card_list) > 0:
                # update the context with the default card
                context.update({"card": card_list[0]})

        return render(self.request, "payment.html", context)

    def post(self, *args, **kwargs):
        order = Order.objects.get(user=self.request.user, ordered=False)

        # Re-validate cart quantities against current stock right before charging.
        for oi in order.items.select_related("item").all():
            try:
                oi.item.ensure_can_fulfill(oi.quantity)
            except ValueError as e:
                messages.warning(self.request, str(e))
                return redirect("core:order-summary")

        form = PaymentForm(self.request.POST)
        userprofile = UserProfile.objects.get(user=self.request.user)
        if not form.is_valid():
            messages.warning(self.request, "Invalid data received")
            return redirect("/payment/stripe/")

        payment_intent_id = self.request.POST.get("payment_intent_id")
        save = form.cleaned_data.get("save")
        use_default = form.cleaned_data.get("use_default")
        token = form.cleaned_data.get("stripeToken")

        # Preferred: PaymentIntents (client confirms via Stripe.js and POSTs payment_intent_id).
        if payment_intent_id:
            try:
                pi = stripe.PaymentIntent.retrieve(payment_intent_id)

                # Require a succeeded PI before finalizing the order. If not yet succeeded,
                # instruct user to retry (this prevents unpaid order finalization).
                if pi["status"] != "succeeded":
                    messages.warning(
                        self.request,
                        f"Payment not completed (status: {pi['status']}). Please try again.",
                    )
                    return redirect("/payment/stripe/")

                # Finalize order (idempotent on our side: only one open cart exists per user).
                payment = Payment.objects.create(
                    stripe_payment_intent_id=pi["id"],
                    stripe_payment_intent_client_secret=pi.get("client_secret"),
                    user=self.request.user,
                    amount=order.get_total(),
                )
                _finalize_order_after_successful_payment(order=order, user=self.request.user, payment=payment)

                messages.success(self.request, "Your order was successful!")
                return redirect("/")

            except ValueError as e:
                messages.warning(self.request, str(e))
                return redirect("core:order-summary")
            except stripe.error.StripeError:
                messages.warning(self.request, "Stripe error while validating payment. Please try again.")
                return redirect("/payment/stripe/")
            except Exception:
                messages.warning(self.request, "A serious error occurred. We have been notifed.")
                return redirect("/payment/stripe/")

        # Fallback: legacy token->Charge flow (preserves existing template behaviour).
        if not token:
            messages.warning(self.request, "Missing payment details. Please try again.")
            return redirect("/payment/stripe/")

        if save:
            if userprofile.stripe_customer_id != "" and userprofile.stripe_customer_id is not None:
                customer = stripe.Customer.retrieve(userprofile.stripe_customer_id)
                customer.sources.create(source=token)
            else:
                customer = stripe.Customer.create(email=self.request.user.email)
                customer.sources.create(source=token)
                userprofile.stripe_customer_id = customer["id"]
                userprofile.one_click_purchasing = True
                userprofile.save()

        amount = int(order.get_total() * 100)

        try:
            if use_default or save:
                # charge the customer because we cannot charge the token more than once
                charge = stripe.Charge.create(
                    amount=amount,  # cents
                    currency="usd",
                    customer=userprofile.stripe_customer_id,
                )
            else:
                # charge once off on the token
                charge = stripe.Charge.create(
                    amount=amount,  # cents
                    currency="usd",
                    source=token,
                )

            payment = Payment.objects.create(
                stripe_charge_id=charge["id"],
                user=self.request.user,
                amount=order.get_total(),
            )
            _finalize_order_after_successful_payment(order=order, user=self.request.user, payment=payment)

            messages.success(self.request, "Your order was successful!")
            return redirect("/")

        except ValueError as e:
            messages.warning(self.request, str(e))
            return redirect("core:order-summary")
        except stripe.error.CardError as e:
            body = e.json_body
            err = body.get("error", {})
            messages.warning(self.request, f"{err.get('message')}")
            return redirect("/")
        except stripe.error.RateLimitError:
            messages.warning(self.request, "Rate limit error")
            return redirect("/")
        except stripe.error.InvalidRequestError as e:
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
            messages.warning(self.request, "Something went wrong. You were not charged. Please try again.")
            return redirect("/")
        except Exception:
            messages.warning(self.request, "A serious error occurred. We have been notifed.")
            return redirect("/")


class HomeView(ListView):
    model = Item
    paginate_by = 10
    template_name = "home.html"


class OrderSummaryView(LoginRequiredMixin, View):
    def get(self, *args, **kwargs):
        try:
            order = Order.objects.get(user=self.request.user, ordered=False)
            context = {"object": order}
            return render(self.request, "order_summary.html", context)
        except ObjectDoesNotExist:
            messages.warning(self.request, "You do not have an active order")
            return redirect("/")


class ItemDetailView(DetailView):
    model = Item
    template_name = "product.html"

    def get_queryset(self):
        # Only allow active items to be viewed on the public storefront.
        # Inactive items remain accessible to admins via admin/API using Item.all_objects.
        return Item.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = context["object"]

        visible_reviews = item.reviews.filter(is_hidden=False).select_related("user").order_by("-created_at", "-id")

        avg = item.average_rating()
        cnt = item.reviews_count()
        dist = item.rating_distribution()

        user_review = None
        can_review = False
        review_form = None

        if self.request.user.is_authenticated:
            user_review = Review.objects.filter(user=self.request.user, item=item).first()
            can_review = user_has_purchased_item(self.request.user, item)
            initial = {}
            if user_review:
                initial = {
                    "rating": user_review.rating,
                    "title": user_review.title or "",
                    "body": user_review.body or "",
                }
            from .review_forms import ReviewForm

            review_form = ReviewForm(initial=initial)

        context.update(
            {
                "reviews": visible_reviews[:20],
                "average_rating": avg,
                "reviews_count": cnt,
                "rating_distribution": dist,
                "user_review": user_review,
                "can_review": can_review,
                "review_form": review_form,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        """Handle create/update/delete of user's review from product page."""
        self.object = self.get_object()
        item = self.object

        if not request.user.is_authenticated:
            messages.warning(request, "Please log in to leave a review.")
            return redirect("account_login")

        action = (request.POST.get("review_action") or "save").lower()

        if action == "delete":
            review = Review.objects.filter(user=request.user, item=item).first()
            if not review:
                messages.info(request, "You do not have a review to delete.")
                return redirect("core:product", slug=item.slug)
            review.delete()
            messages.success(request, "Your review was deleted.")
            return redirect("core:product", slug=item.slug)

        # save/update
        if not user_has_purchased_item(request.user, item):
            messages.warning(request, "Only customers who purchased this item can leave a review.")
            return redirect("core:product", slug=item.slug)

        review = Review.objects.filter(user=request.user, item=item).first()
        from .review_forms import ReviewForm

        form = ReviewForm(request.POST)
        if not form.is_valid():
            # Re-render the page with validation messages
            ctx = self.get_context_data()
            ctx["review_form"] = form
            messages.warning(request, "Please fix the errors in your review form.")
            return render(request, "product.html", ctx)

        rating = int(form.cleaned_data["rating"])
        title = (form.cleaned_data.get("title") or "").strip()
        body = form.cleaned_data["body"]

        try:
            if review is None:
                review = Review(user=request.user, item=item)
            review.rating = rating
            review.title = title
            review.body = body
            review.full_clean()
            review.save()
        except Exception as e:
            messages.warning(request, str(e))
            return redirect("core:product", slug=item.slug)

        messages.success(request, "Thanks! Your review has been saved.")
        return redirect("core:product", slug=item.slug)


@login_required
def add_to_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)

    # Disallow adding when out of stock (when tracking inventory)
    if item.track_inventory and item.stock_quantity <= 0:
        messages.warning(request, "This item is out of stock.")
        return redirect("core:product", slug=slug)

    order_item, created = OrderItem.objects.get_or_create(item=item, user=request.user, ordered=False)
    order_qs = Order.objects.filter(user=request.user, ordered=False)
    if order_qs.exists():
        order = order_qs[0]
        # check if the order item is in the order
        if order.items.filter(item__slug=item.slug).exists():
            next_qty = order_item.quantity + 1
            if item.track_inventory and next_qty > item.stock_quantity:
                messages.warning(
                    request,
                    f"Only {item.stock_quantity} left in stock; you already have {order_item.quantity} in your cart.",
                )
                return redirect("core:order-summary")
            order_item.quantity = next_qty
            order_item.save()
            messages.info(request, "This item quantity was updated.")
            return redirect("core:order-summary")
        # First time adding: ensure at least 1 is allowed
        if item.track_inventory and order_item.quantity > item.stock_quantity:
            messages.warning(request, f"Only {item.stock_quantity} left in stock.")
            return redirect("core:order-summary")
        order.items.add(order_item)
        messages.info(request, "This item was added to your cart.")
        return redirect("core:order-summary")

    ordered_date = timezone.now()
    order = Order.objects.create(user=request.user, ordered_date=ordered_date)
    order.items.add(order_item)
    messages.info(request, "This item was added to your cart.")
    return redirect("core:order-summary")


@login_required
def remove_from_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_qs = Order.objects.filter(
        user=request.user,
        ordered=False,
    )
    if order_qs.exists():
        order = order_qs[0]
        # check if the order item is in the order
        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.filter(
                item=item,
                user=request.user,
                ordered=False,
            )[0]
            order.items.remove(order_item)
            order_item.delete()
            messages.info(request, "This item was removed from your cart.")
            return redirect("core:order-summary")
        messages.info(request, "This item was not in your cart")
        return redirect("core:product", slug=slug)

    messages.info(request, "You do not have an active order")
    return redirect("core:product", slug=slug)


@login_required
def remove_single_item_from_cart(request, slug):
    item = get_object_or_404(Item, slug=slug)
    order_qs = Order.objects.filter(
        user=request.user,
        ordered=False,
    )
    if order_qs.exists():
        order = order_qs[0]
        # check if the order item is in the order
        if order.items.filter(item__slug=item.slug).exists():
            order_item = OrderItem.objects.filter(
                item=item,
                user=request.user,
                ordered=False,
            )[0]
            if order_item.quantity > 1:
                order_item.quantity -= 1
                order_item.save()
            else:
                order.items.remove(order_item)
            messages.info(request, "This item quantity was updated.")
            return redirect("core:order-summary")
        messages.info(request, "This item was not in your cart")
        return redirect("core:product", slug=slug)

    messages.info(request, "You do not have an active order")
    return redirect("core:product", slug=slug)


def get_coupon(request, code: str):
    """Fetch coupon by code (case-insensitive)."""
    if not code:
        return None
    try:
        coupon = Coupon.objects.get(code__iexact=code.strip())
        return coupon
    except ObjectDoesNotExist:
        return None


class AddCouponView(View):
    def post(self, *args, **kwargs):
        form = CouponForm(self.request.POST or None)
        if not form.is_valid():
            messages.warning(self.request, "Invalid coupon form.")
            return redirect("core:checkout")

        try:
            code = form.cleaned_data.get("code")
            order = Order.objects.get(user=self.request.user, ordered=False)

            coupon = get_coupon(self.request, code)
            if not coupon:
                messages.info(self.request, "This coupon does not exist")
                return redirect("core:checkout")

            try:
                order.apply_coupon(coupon, user=self.request.user)
            except ValueError as e:
                messages.warning(self.request, str(e))
                return redirect("core:checkout")

            order.save()
            messages.success(self.request, "Coupon applied.")
            return redirect("core:checkout")
        except ObjectDoesNotExist:
            messages.info(self.request, "You do not have an active order")
            return redirect("core:checkout")


# PUBLIC_INTERFACE
@login_required
def remove_coupon(request):
    """Remove currently-applied coupon from the active cart (idempotent)."""
    try:
        order = Order.objects.get(user=request.user, ordered=False)
    except ObjectDoesNotExist:
        messages.info(request, "You do not have an active order")
        return redirect("core:order-summary")

    order.remove_coupon()
    order.save()
    messages.success(request, "Coupon removed.")
    return redirect("core:checkout")


class RequestRefundView(View):
    def get(self, *args, **kwargs):
        form = RefundForm()
        context = {"form": form}
        return render(self.request, "request_refund.html", context)

    def post(self, *args, **kwargs):
        form = RefundForm(self.request.POST)
        if form.is_valid():
            ref_code = form.cleaned_data.get("ref_code")
            message = form.cleaned_data.get("message")
            email = form.cleaned_data.get("email")
            # edit the order
            try:
                order = Order.objects.get(ref_code=ref_code)
                order.refund_requested = True
                order.save()

                # store the refund
                refund = Refund()
                refund.order = order
                refund.reason = message
                refund.email = email
                refund.save()

                messages.info(self.request, "Your request was received.")
                return redirect("core:request-refund")

            except ObjectDoesNotExist:
                messages.info(self.request, "This order does not exist.")
                return redirect("core:request-refund")


# --- Admin-only template views -------------------------------------------------
# We do NOT alter public storefront/cart/checkout views. These views are opt-in
# endpoints intended for staff/admin operations if used in templates later.


# PUBLIC_INTERFACE
@user_passes_test(request_is_admin)
def admin_order_list(request):
    """Admin-only: list all orders for operations.

    This does not change customer flows; it is a separate management view.
    """
    orders = Order.objects.all().order_by("-start_date")
    return render(request, "admin/order_list.html", {"orders": orders})


# PUBLIC_INTERFACE
@user_passes_test(request_is_admin)
def admin_order_transition(request, order_id: int):
    """Admin-only: transition an order status via a simple POST.

    Uses explicit status lifecycle with validation:
      placed -> shipped -> delivered
    """
    order = get_object_or_404(Order, pk=order_id)

    if request.method != "POST":
        # Render a small management form
        return render(request, "admin/order_transition.html", {"order": order})

    new_status = request.POST.get("new_status")
    refund_granted = request.POST.get("refund_granted")

    # Refund flag is independent from shipping lifecycle.
    order.refund_granted = refund_granted is not None

    # Prevent lifecycle transitions on unpaid carts.
    if new_status in {Order.OrderStatus.SHIPPED, Order.OrderStatus.DELIVERED} and not order.ordered:
        messages.warning(request, "Cannot ship/deliver an unpaid order (cart).")
        return redirect("core:admin-order-transition", order_id=order.id)

    if new_status:
        try:
            order.transition_to(new_status, actor=request.user)
        except ValueError as e:
            messages.warning(request, str(e))
            return redirect("core:admin-order-transition", order_id=order.id)

    order.save()
    messages.success(request, "Order updated.")
    return redirect("core:admin-order-list")


# PUBLIC_INTERFACE
@login_required
def my_orders(request):
    """User-facing: show a list of the user's paid orders with lifecycle status."""
    orders = Order.objects.filter(user=request.user, ordered=True).order_by("-ordered_date")
    return render(request, "my_orders.html", {"orders": orders})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_me(request):
    """Return basic identity information for the authenticated user.

    This endpoint is intentionally minimal and exists to confirm that:
    - JWT token obtain works (POST /api/auth/token/)
    - Authorization header processing works (Bearer access token)
    - DRF + SimpleJWT permissions enforce authentication

    Returns:
        JSON with user id, username, email, and staff/superuser flags.
    """
    user = request.user
    return Response(
        {
            "id": user.id,
            "username": user.get_username(),
            "email": user.email,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }
    )
