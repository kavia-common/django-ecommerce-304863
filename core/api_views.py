"""
Core DRF API views.

These API endpoints are separate from template-based routes and are intended for
programmatic access (mobile apps, SPA, admin dashboards, etc.).

RBAC strategy:
- Public endpoints:
  - AllowAny + read-only access (GET/HEAD/OPTIONS)
- Authenticated user endpoints:
  - IsAuthenticated and user-scoped queryset access (object-level checks)
- Admin endpoints:
  - IsAuthenticated + Admin group OR required Django model permissions

We use Django's built-in Groups/Permissions system (see migration 0005_...).

Order API requirements implemented here:
- User:
  - GET /api/orders/active/             active cart / checkout summary
  - GET /api/orders/                   list user's orders
  - GET /api/orders/{id}/              retrieve user's order details
- Admin:
  - GET /api/admin/orders/             list/filter orders
  - GET /api/admin/orders/{id}/        retrieve an order
  - POST /api/admin/orders/{id}/transition/  status transition (idempotent)

Idempotency:
- Status transitions accept an idempotency key via JSON payload or `Idempotency-Key` header.
- Existing Order.transition_status() + OrderStatusHistory uniqueness enforce idempotency.
"""

from __future__ import annotations

from typing import Optional

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.inventory import (
    commit_inventory_for_paid_order,
    release_inventory_reservations_for_order,
    reserve_inventory_for_order,
    restock_inventory_for_order_refund,
)
from core.models import Address, Coupon, Item, Order, OrderItem, OrderStatusHistory, Payment, Refund
from core.payment_service import PaymentResultCode, attempt_payment_for_order, get_payment_mode
from core.permissions import IsAdminGroupOrDjangoPermission


def _get_idempotency_key_from_request(request) -> Optional[str]:
    """
    Read idempotency key from request header.

    We support the de-facto standard `Idempotency-Key` header.
    """
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return None
    key = str(key).strip()
    return key or None


class HealthAPIView(APIView):
    """Simple health check endpoint to verify DRF wiring."""

    permission_classes = [AllowAny]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """Return a small payload indicating the API is reachable."""
        return Response({"status": "ok"})


# -------------------------
# Serializers
# -------------------------


class ItemSerializer(serializers.ModelSerializer):
    """Read-only item summary for order contexts."""

    class Meta:
        model = Item
        fields = [
            "id",
            "title",
            "price",
            "discount_price",
            "category",
            "label",
            "slug",
            "description",
            "image",
        ]


class AddressSerializer(serializers.ModelSerializer):
    """Address representation used for order shipping/billing summaries."""

    class Meta:
        model = Address
        fields = [
            "id",
            "street_address",
            "apartment_address",
            "country",
            "zip",
            "address_type",
            "default",
        ]


class PaymentSummarySerializer(serializers.ModelSerializer):
    """Payment summary exposed on orders (provider-agnostic)."""

    class Meta:
        model = Payment
        fields = [
            "id",
            "provider",
            "mode",
            "provider_reference",
            "idempotency_key",
            "status",
            "error_message",
            "timestamp",
            "amount",
        ]


class CouponSummarySerializer(serializers.ModelSerializer):
    """Coupon summary exposed on orders."""

    class Meta:
        model = Coupon
        fields = ["id", "code", "amount"]


class AdminCouponSerializer(serializers.ModelSerializer):
    """Admin serializer for managing coupons."""

    class Meta:
        model = Coupon
        fields = ["id", "code", "amount"]


# -------------------------
# Admin coupon endpoints
# -------------------------


class AdminCouponListCreateAPIView(APIView):
    """
    Admin: list and create coupons.

    Routes:
      - GET  /api/admin/coupons/
      - POST /api/admin/coupons/

    Permissions:
      - Admin group OR Django permissions:
        - core.view_coupon for GET
        - core.add_coupon for POST
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_coupon", "core.add_coupon")

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List coupons (admin)."""
        coupons = Coupon.objects.all().order_by("-id")
        return Response(AdminCouponSerializer(coupons, many=True).data)

    # PUBLIC_INTERFACE
    def post(self, request, *args, **kwargs):
        """Create a coupon (admin)."""
        ser = AdminCouponSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        coupon = ser.save()
        return Response(AdminCouponSerializer(coupon).data, status=status.HTTP_201_CREATED)


class AdminCouponDetailAPIView(APIView):
    """
    Admin: retrieve/update/delete a coupon.

    Routes:
      - GET    /api/admin/coupons/{coupon_id}/
      - PUT    /api/admin/coupons/{coupon_id}/
      - PATCH  /api/admin/coupons/{coupon_id}/
      - DELETE /api/admin/coupons/{coupon_id}/

    Permissions:
      - Admin group OR Django permissions:
        - core.view_coupon for GET
        - core.change_coupon for PUT/PATCH
        - core.delete_coupon for DELETE
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_coupon", "core.change_coupon", "core.delete_coupon")

    # PUBLIC_INTERFACE
    def get(self, request, coupon_id: int, *args, **kwargs):
        """Retrieve a coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        return Response(AdminCouponSerializer(coupon).data)

    # PUBLIC_INTERFACE
    def put(self, request, coupon_id: int, *args, **kwargs):
        """Replace a coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        ser = AdminCouponSerializer(instance=coupon, data=request.data)
        ser.is_valid(raise_exception=True)
        coupon = ser.save()
        return Response(AdminCouponSerializer(coupon).data)

    # PUBLIC_INTERFACE
    def patch(self, request, coupon_id: int, *args, **kwargs):
        """Partially update a coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        ser = AdminCouponSerializer(instance=coupon, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        coupon = ser.save()
        return Response(AdminCouponSerializer(coupon).data)

    # PUBLIC_INTERFACE
    def delete(self, request, coupon_id: int, *args, **kwargs):
        """Delete a coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        coupon.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderItemSerializer(serializers.ModelSerializer):
    """OrderItem serializer embedding an item summary and pricing totals."""

    item = ItemSerializer(read_only=True)

    final_price = serializers.SerializerMethodField()
    total_item_price = serializers.SerializerMethodField()
    total_discount_item_price = serializers.SerializerMethodField()
    amount_saved = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "ordered",
            "quantity",
            "item",
            # Inventory tracking
            "quantity_reserved",
            "quantity_committed",
            "quantity_restocked",
            # Pricing helpers
            "total_item_price",
            "total_discount_item_price",
            "amount_saved",
            "final_price",
        ]
        read_only_fields = fields

    def get_total_item_price(self, obj) -> float:
        return float(obj.get_total_item_price())

    def get_total_discount_item_price(self, obj) -> float:
        return float(obj.get_total_discount_item_price())

    def get_amount_saved(self, obj) -> float:
        return float(obj.get_amount_saved())

    def get_final_price(self, obj) -> float:
        return float(obj.get_final_price())


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    """Order status transition audit log."""

    performed_by_id = serializers.IntegerField(source="performed_by.id", read_only=True)
    performed_by_username = serializers.CharField(source="performed_by.username", read_only=True)

    class Meta:
        model = OrderStatusHistory
        fields = [
            "id",
            "from_status",
            "to_status",
            "performed_at",
            "performed_by_id",
            "performed_by_username",
            "idempotency_key",
            "reason",
            "metadata",
        ]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    """
    User-facing order representation.

    Includes:
    - items (with item summaries)
    - totals
    - coupon summary
    - shipping/billing addresses
    - payment summary (if present)

    NOTE: For customers we do not expose full status history by default; admins
    get it via AdminOrderSerializer.
    """

    items = OrderItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    coupon = CouponSummarySerializer(read_only=True)
    shipping_address = AddressSerializer(read_only=True)
    billing_address = AddressSerializer(read_only=True)
    payment = PaymentSummarySerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "ref_code",
            "status",
            "ordered",
            "ordered_date",
            # legacy flags retained for compatibility
            "being_delivered",
            "received",
            "refund_requested",
            "refund_granted",
            # relationships / summaries
            "items",
            "shipping_address",
            "billing_address",
            "payment",
            "coupon",
            "total",
            "start_date",
        ]
        read_only_fields = fields

    def get_total(self, obj) -> float:
        return float(obj.get_total())


class AdminOrderSerializer(OrderSerializer):
    """
    Admin-facing order representation includes immutable status history.

    This is useful for admin dashboards and audit tooling.
    """

    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ["status_history"]


class OrderCheckoutSummarySerializer(serializers.Serializer):
    """
    Active cart / checkout summary for the current user.

    This endpoint is intended for UIs to render a checkout summary without mutating state.
    """

    order = OrderSerializer(allow_null=True)
    has_active_order = serializers.BooleanField()
    payment_mode = serializers.CharField()
    totals = serializers.DictField()
    notes = serializers.ListField(child=serializers.CharField())


class AdminOrderTransitionSerializer(serializers.Serializer):
    """
    Admin transition request payload.

    - target_status: required new status.
    - idempotency_key: optional but strongly recommended so clients can safely retry.
    - reason/metadata: optional audit context.

    You can also provide the idempotency key via `Idempotency-Key` header; if both
    are present, body wins.
    """

    target_status = serializers.ChoiceField(choices=Order.Status.choices)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=128)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    metadata = serializers.JSONField(required=False)


class DummyPaymentSimulateSerializer(serializers.Serializer):
    """
    Dummy payment simulation payload.

    outcome:
      - 'success' or 'fail' (optional). If omitted, uses server dummy settings.
    idempotency_key:
      - optional, recommended for retry safety.
    """

    outcome = serializers.ChoiceField(choices=[("success", "success"), ("fail", "fail")], required=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=128)


# -------------------------
# Public endpoints (read-only)
# -------------------------


class PublicItemListAPIView(APIView):
    """
    Public: list products.

    - Read-only (GET/HEAD/OPTIONS).
    - No authentication required.
    """

    permission_classes = [AllowAny]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List products (public)."""
        items = Item.objects.all().order_by("id")
        return Response(ItemSerializer(items, many=True).data)


class PublicItemDetailAPIView(APIView):
    """
    Public: retrieve a product by id.

    - Read-only (GET/HEAD/OPTIONS).
    - No authentication required.
    """

    permission_classes = [AllowAny]

    # PUBLIC_INTERFACE
    def get(self, request, item_id: int, *args, **kwargs):
        """Retrieve a product (public)."""
        item = get_object_or_404(Item, pk=item_id)
        return Response(ItemSerializer(item).data)


# -------------------------
# Authenticated user endpoints (customer scope)
# -------------------------


class MyActiveOrderCheckoutSummaryAPIView(APIView):
    """
    Customer: get active cart / checkout summary.

    Route:
      GET /api/orders/active/

    Behavior:
      - Returns the most recent active (ordered=False) order for the user if present.
      - Does NOT reserve inventory or attempt payment (read-only summary).
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """Return the authenticated user's active cart/checkout summary."""
        order = (
            Order.objects.filter(user=request.user, ordered=False)
            .prefetch_related("items__item")
            .select_related("shipping_address", "billing_address", "payment", "coupon")
            .order_by("-id")
            .first()
        )

        totals = {"subtotal": 0.0, "coupon_amount": 0.0, "total": 0.0}
        notes: list[str] = []

        if order:
            totals["total"] = float(order.get_total())
            # Subtotal (before coupon) is derived from items only.
            subtotal = 0.0
            for oi in order.items.all():
                subtotal += float(oi.get_final_price())
            totals["subtotal"] = float(subtotal)
            totals["coupon_amount"] = float(order.coupon.amount) if order.coupon else 0.0
        else:
            notes.append("No active order.")

        return Response(
            OrderCheckoutSummarySerializer(
                {
                    "order": OrderSerializer(order).data if order else None,
                    "has_active_order": bool(order),
                    "payment_mode": get_payment_mode(),
                    "totals": totals,
                    "notes": notes,
                }
            ).data
        )


class MyOrdersListAPIView(APIView):
    """
    Customer: list the authenticated user's orders.

    Route:
      GET /api/orders/

    JWT-protected (or session auth) via IsAuthenticated.
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List orders for the current user (new canonical route)."""
        orders = (
            Order.objects.filter(user=request.user)
            .prefetch_related("items__item")
            .select_related("shipping_address", "billing_address", "payment", "coupon")
            .order_by("-id")
        )
        return Response(OrderSerializer(orders, many=True).data)


class MyOrderDetailAPIView(APIView):
    """
    Customer: retrieve an order that belongs to the authenticated user.

    Route:
      GET /api/orders/{id}/

    Object-level access enforcement:
    - 404 if the order does not belong to the requesting user.
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def get(self, request, order_id: int, *args, **kwargs):
        """Retrieve one order for the current user."""
        order = (
            Order.objects.filter(pk=order_id, user=request.user)
            .prefetch_related("items__item")
            .select_related("shipping_address", "billing_address", "payment", "coupon")
            .first()
        )
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrderSerializer(order).data)


# -------------------------
# Admin-only endpoints
# -------------------------


class AdminOrderListAPIView(APIView):
    """
    Admin: list/filter orders.

    Route:
      GET /api/admin/orders/

    Supported query params:
      - status=CREATED|PAID|FULFILLING|SHIPPED|DELIVERED|CANCELLED|REFUNDED
      - user_id=<int>
      - ordered=true|false
      - q=<string> (matches ref_code, username)
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_order",)

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List orders (admin) with basic filtering."""
        qs = (
            Order.objects.all()
            .prefetch_related("items__item", "status_history")
            .select_related("user", "shipping_address", "billing_address", "payment", "coupon")
            .order_by("-id")
        )

        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        user_id = request.query_params.get("user_id")
        if user_id:
            try:
                qs = qs.filter(user_id=int(user_id))
            except (TypeError, ValueError):
                return Response({"detail": "Invalid user_id."}, status=status.HTTP_400_BAD_REQUEST)

        ordered_param = request.query_params.get("ordered")
        if ordered_param is not None and ordered_param != "":
            val = str(ordered_param).lower()
            if val in ("true", "1", "yes"):
                qs = qs.filter(ordered=True)
            elif val in ("false", "0", "no"):
                qs = qs.filter(ordered=False)
            else:
                return Response({"detail": "Invalid ordered param (use true/false)."}, status=status.HTTP_400_BAD_REQUEST)

        q = request.query_params.get("q")
        if q:
            # Use Q objects; OR-ing querysets (`qs1 | qs2`) can break other filters/order_by.
            from django.db.models import Q

            qs = qs.filter(Q(ref_code__icontains=q) | Q(user__username__icontains=q))

        return Response(AdminOrderSerializer(qs, many=True).data)


class AdminOrderDetailAPIView(APIView):
    """
    Admin: retrieve an order.

    Route:
      GET /api/admin/orders/{id}/
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_order",)

    # PUBLIC_INTERFACE
    def get(self, request, order_id: int, *args, **kwargs):
        """Retrieve one order (admin)."""
        order = (
            Order.objects.filter(pk=order_id)
            .prefetch_related("items__item", "status_history")
            .select_related("user", "shipping_address", "billing_address", "payment", "coupon")
            .first()
        )
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AdminOrderSerializer(order).data)


class AdminOrderStatusTransitionAPIView(APIView):
    """
    Admin: transition order status (explicit lifecycle).

    Route:
      POST /api/admin/orders/{id}/transition/

    This is the canonical way to move orders through:
      CREATED -> PAID -> FULFILLING -> SHIPPED -> DELIVERED (+ CANCELLED/REFUNDED).

    Idempotency:
      Provide an `idempotency_key` so retries do not duplicate state transitions. If a
      history record already exists for the given (order, idempotency_key), we return
      that history record and the order (no changes applied).

    Requires Admin group OR relevant model permissions:
    - core.change_order
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.change_order",)

    # PUBLIC_INTERFACE
    def post(self, request, order_id: int, *args, **kwargs):
        """Transition order status (admin)."""
        order = get_object_or_404(Order, pk=order_id)
        ser = AdminOrderTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        payload = ser.validated_data

        idempotency_key = payload.get("idempotency_key")
        if idempotency_key in ("", None):
            # fallback to header if body isn't provided
            idempotency_key = _get_idempotency_key_from_request(request)

        target_status = payload["target_status"]

        # Inventory actions should be tied to status changes to keep domain consistent.
        # NOTE: We perform the inventory operation *before* the transition where it matters:
        # - PAID: ensure reservation exists then commit.
        # - CANCELLED: release any outstanding reservations.
        # - REFUNDED: restock (assumes committed previously).
        try:
            if target_status == Order.Status.PAID:
                reserve_inventory_for_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-reserve:{order.id}:{idempotency_key or target_status}",
                )
                commit_inventory_for_paid_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-commit:{order.id}:{idempotency_key or target_status}",
                )
            elif target_status == Order.Status.CANCELLED:
                release_inventory_reservations_for_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-release:{order.id}:{idempotency_key or target_status}",
                    reason="Released reservation due to admin cancellation",
                )
            elif target_status == Order.Status.REFUNDED:
                restock_inventory_for_order_refund(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-restock:{order.id}:{idempotency_key or target_status}",
                )
        except Exception as e:
            return Response({"detail": f"Inventory operation failed: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            history = order.transition_status(
                target_status=target_status,
                performed_by=request.user,
                reason=payload.get("reason") or None,
                idempotency_key=idempotency_key,
                metadata=payload.get("metadata") or None,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        order.refresh_from_db()
        return Response(
            {
                "order": AdminOrderSerializer(order).data,
                "transition": OrderStatusHistorySerializer(history).data,
            }
        )


class DummyPaymentSimulateAPIView(APIView):
    """
    Customer: simulate a payment intent in dummy mode for the active (un-ordered) order.

    This endpoint is intentionally minimal and only works when PAYMENT_MODE resolves to 'dummy'.

    Response:
      - 200 with payment result + order id when succeeded/failed.
      - 400 if not in dummy mode or no active order.
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def post(self, request, *args, **kwargs):
        """Simulate payment for current user's active order (dummy mode only)."""
        if get_payment_mode() != "dummy":
            return Response(
                {"detail": "Dummy simulation is only available when payment mode is 'dummy'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = Order.objects.filter(user=request.user, ordered=False).order_by("-id").first()
        if not order:
            return Response({"detail": "No active order to pay."}, status=status.HTTP_400_BAD_REQUEST)

        ser = DummyPaymentSimulateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        outcome = ser.validated_data.get("outcome")
        idem = ser.validated_data.get("idempotency_key") or None
        if idem == "":
            idem = None

        # Ensure reservation exists (safe/idempotent).
        try:
            reserve_inventory_for_order(
                order=order,
                performed_by=request.user,
                idempotency_key=f"api-dummy-reserve:{order.id}:{idem or 'default'}",
            )
        except Exception as e:
            return Response({"detail": f"Unable to reserve inventory: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        result = attempt_payment_for_order(
            order=order,
            user=request.user,
            amount=order.get_total(),
            currency="usd",
            idempotency_key=idem or f"api-dummy-pay:{order.id}",
            dummy_force_outcome=outcome,
            extra_metadata={"source": "DummyPaymentSimulateAPIView"},
        )

        if result.code == PaymentResultCode.SUCCEEDED and result.payment:
            # Commit inventory and transition order to paid.
            commit_inventory_for_paid_order(
                order=order,
                performed_by=request.user,
                idempotency_key=f"api-dummy-commit:{order.id}:{result.payment.idempotency_key}",
            )
            order.ordered = True
            order.payment = result.payment
            order.ref_code = order.ref_code or f"api_dummy_{order.id}"
            try:
                order.transition_status(
                    target_status=Order.Status.PAID,
                    performed_by=request.user,
                    reason="Payment succeeded (dummy)",
                    idempotency_key=f"api-dummy-paid:{order.id}:{result.payment.idempotency_key}",
                    metadata={"payment_id": result.payment.id, "provider_reference": result.provider_reference},
                )
            except Exception:
                order.save()

            return Response(
                {
                    "order_id": order.id,
                    "payment_id": result.payment.id,
                    "status": "SUCCEEDED",
                    "provider_reference": result.provider_reference,
                }
            )

        # Failure: release inventory reservation and return message.
        release_inventory_reservations_for_order(
            order=order,
            performed_by=request.user,
            idempotency_key=f"api-dummy-failed:{order.id}:{result.code}",
            reason="Released reservation due to dummy payment failure",
        )

        return Response(
            {
                "order_id": order.id,
                "payment_id": result.payment.id if result.payment else None,
                "status": "FAILED",
                "code": result.code,
                "message": result.message,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class AdminRefundModerationAPIView(APIView):
    """
    Admin: moderate refunds (accept/deny).

    We keep moderation at the Refund record level, but update the corresponding order
    flags to match the site's admin action behavior.

    Requires Admin group OR relevant model permissions:
    - core.change_refund / core.change_order
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.change_refund", "core.change_order")

    # PUBLIC_INTERFACE
    def post(self, request, refund_id: int, *args, **kwargs):
        """
        Accept/deny a refund.

        Body:
          { "accepted": true|false }
        """
        refund = get_object_or_404(Refund, pk=refund_id)
        accepted = request.data.get("accepted", None)
        if accepted is None:
            return Response(
                {"detail": "Field 'accepted' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refund.accepted = bool(accepted)
        refund.save(update_fields=["accepted"])

        # Mirror admin action behavior on the related order.
        order = refund.order
        if refund.accepted:
            # Restock idempotently (safe if moderation endpoint is called multiple times).
            restock_inventory_for_order_refund(
                order=order,
                performed_by=request.user,
                idempotency_key=f"refund:{refund.id}:restock",
            )
            # Transition to REFUNDED; idempotency key ensures repeat moderation calls are safe.
            order.transition_status(
                target_status=Order.Status.REFUNDED,
                performed_by=request.user,
                reason="Refund accepted via AdminRefundModerationAPIView",
                idempotency_key=f"refund:{refund.id}:accepted",
                metadata={"refund_id": refund.id},
            )
        else:
            # Denied: keep order in its current status, just ensure legacy flags align with denial.
            order.refund_granted = False
            order.save(update_fields=["refund_granted"])

        return Response({"id": refund.id, "accepted": refund.accepted})
