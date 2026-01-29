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
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Coupon, Item, Order, Refund
from core.permissions import IsAdminGroupOrDjangoPermission


class HealthAPIView(APIView):
    """Simple health check endpoint to verify DRF wiring."""

    permission_classes = [AllowAny]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """Return a small payload indicating the API is reachable."""
        return Response({"status": "ok"})


# -------------------------
# Serializers (minimal)
# -------------------------


class ItemSerializer(serializers.ModelSerializer):
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


class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ["id", "code", "amount"]


class OrderSerializer(serializers.ModelSerializer):
    """
    Minimal order representation for API clients.

    Note: We don't embed full OrderItem details here to keep the API surface small.
    """

    total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "ref_code",
            "ordered",
            "ordered_date",
            "being_delivered",
            "received",
            "refund_requested",
            "refund_granted",
            "total",
        ]

    def get_total(self, obj) -> float:
        return obj.get_total()


class OrderStatusTransitionSerializer(serializers.Serializer):
    being_delivered = serializers.BooleanField(required=False)
    received = serializers.BooleanField(required=False)
    refund_requested = serializers.BooleanField(required=False)
    refund_granted = serializers.BooleanField(required=False)


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


class MyOrdersListAPIView(APIView):
    """
    Customer: list the authenticated user's orders.

    JWT-protected (or session auth) via IsAuthenticated.
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List orders for the current user."""
        orders = Order.objects.filter(user=request.user).order_by("-id")
        return Response(OrderSerializer(orders, many=True).data)


class MyOrderDetailAPIView(APIView):
    """
    Customer: retrieve an order that belongs to the authenticated user.

    Object-level access enforcement:
    - 404 if the order does not belong to the requesting user.
    """

    permission_classes = [IsAuthenticated]

    # PUBLIC_INTERFACE
    def get(self, request, order_id: int, *args, **kwargs):
        """Retrieve one order for the current user."""
        order = get_object_or_404(Order, pk=order_id, user=request.user)
        return Response(OrderSerializer(order).data)


# -------------------------
# Admin-only endpoints
# -------------------------


class AdminItemListCreateAPIView(APIView):
    """
    Admin: list/create products.

    Requires Admin group OR relevant model permissions:
    - core.view_item / core.add_item
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_item", "core.add_item")

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List all products (admin)."""
        items = Item.objects.all().order_by("id")
        return Response(ItemSerializer(items, many=True).data)

    # PUBLIC_INTERFACE
    def post(self, request, *args, **kwargs):
        """Create a product (admin)."""
        ser = ItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        item = ser.save()
        return Response(ItemSerializer(item).data, status=status.HTTP_201_CREATED)


class AdminItemDetailAPIView(APIView):
    """
    Admin: retrieve/update/delete a product by id.

    Requires Admin group OR relevant model permissions:
    - core.view_item / core.change_item / core.delete_item
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_item", "core.change_item", "core.delete_item")

    # PUBLIC_INTERFACE
    def get(self, request, item_id: int, *args, **kwargs):
        """Retrieve a product (admin)."""
        item = get_object_or_404(Item, pk=item_id)
        return Response(ItemSerializer(item).data)

    # PUBLIC_INTERFACE
    def put(self, request, item_id: int, *args, **kwargs):
        """Update a product (admin)."""
        item = get_object_or_404(Item, pk=item_id)
        ser = ItemSerializer(instance=item, data=request.data)
        ser.is_valid(raise_exception=True)
        item = ser.save()
        return Response(ItemSerializer(item).data)

    # PUBLIC_INTERFACE
    def patch(self, request, item_id: int, *args, **kwargs):
        """Partially update a product (admin)."""
        item = get_object_or_404(Item, pk=item_id)
        ser = ItemSerializer(instance=item, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        item = ser.save()
        return Response(ItemSerializer(item).data)

    # PUBLIC_INTERFACE
    def delete(self, request, item_id: int, *args, **kwargs):
        """Delete a product (admin)."""
        item = get_object_or_404(Item, pk=item_id)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminCouponListCreateAPIView(APIView):
    """
    Admin: list/create coupons.

    Requires Admin group OR relevant model permissions:
    - core.view_coupon / core.add_coupon
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.view_coupon", "core.add_coupon")

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """List coupons (admin)."""
        coupons = Coupon.objects.all().order_by("id")
        return Response(CouponSerializer(coupons, many=True).data)

    # PUBLIC_INTERFACE
    def post(self, request, *args, **kwargs):
        """Create coupon (admin)."""
        ser = CouponSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        coupon = ser.save()
        return Response(CouponSerializer(coupon).data, status=status.HTTP_201_CREATED)


class AdminCouponDetailAPIView(APIView):
    """
    Admin: update/delete coupon.

    Requires Admin group OR relevant model permissions:
    - core.change_coupon / core.delete_coupon / core.view_coupon
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.change_coupon", "core.delete_coupon", "core.view_coupon")

    # PUBLIC_INTERFACE
    def patch(self, request, coupon_id: int, *args, **kwargs):
        """Update coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        ser = CouponSerializer(instance=coupon, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        coupon = ser.save()
        return Response(CouponSerializer(coupon).data)

    # PUBLIC_INTERFACE
    def delete(self, request, coupon_id: int, *args, **kwargs):
        """Delete coupon (admin)."""
        coupon = get_object_or_404(Coupon, pk=coupon_id)
        coupon.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminOrderStatusTransitionAPIView(APIView):
    """
    Admin: transition order status flags.

    Note: The legacy data model uses booleans (being_delivered/received/refund_*).
    This endpoint exposes controlled transitions for admin operations.

    Requires Admin group OR relevant model permissions:
    - core.change_order
    """

    permission_classes = [IsAuthenticated, IsAdminGroupOrDjangoPermission]
    required_django_perms = ("core.change_order",)

    # PUBLIC_INTERFACE
    def post(self, request, order_id: int, *args, **kwargs):
        """Update order status flags (admin)."""
        order = get_object_or_404(Order, pk=order_id)
        ser = OrderStatusTransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        data = ser.validated_data
        # Only update provided fields.
        for field in ["being_delivered", "received", "refund_requested", "refund_granted"]:
            if field in data:
                setattr(order, field, data[field])

        order.save(update_fields=[k for k in data.keys()])
        return Response({"id": order.id, "updated": list(data.keys())})


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
            order.refund_requested = False
            order.refund_granted = True
        else:
            order.refund_granted = False
        order.save(update_fields=["refund_requested", "refund_granted"])

        return Response({"id": refund.id, "accepted": refund.accepted})
