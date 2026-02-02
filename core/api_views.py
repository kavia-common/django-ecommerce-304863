"""DRF API endpoints.

These endpoints are under /api/** and use JWT (SimpleJWT) authentication as configured in settings.

RBAC enforcement:
- All endpoints require authentication.
- Admin-only endpoints additionally require IsAdminRole.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api_permissions import IsAdminRole
from .models import Item, Order


class ItemSerializer(serializers.ModelSerializer):
    """Serializer for Item product CRUD."""

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


class InventoryAdjustRequest(serializers.Serializer):
    """Request payload for inventory adjustments."""

    item_id = serializers.IntegerField(help_text="Item ID to adjust.")
    delta = serializers.IntegerField(help_text="Stock delta (positive or negative).")


class OrderStatusTransitionRequest(serializers.Serializer):
    """Request payload for admin order status transitions."""

    new_status = serializers.ChoiceField(
        choices=[c.value for c in Order.OrderStatus],
        help_text="Target order status.",
    )


class OrderAdminSerializer(serializers.ModelSerializer):
    """Serializer for admin order management views."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    history = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "user",
            "ref_code",
            "ordered",
            "ordered_date",
            "status",
            "status_display",
            "placed_at",
            "shipped_at",
            "delivered_at",
            "history",
            # legacy
            "being_delivered",
            "received",
            "refund_requested",
            "refund_granted",
        ]

    def get_history(self, obj):
        return obj.status_history()


class OrderMeSerializer(serializers.ModelSerializer):
    """Serializer for user-facing order view."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    history = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "ref_code",
            "ordered_date",
            "status",
            "status_display",
            "placed_at",
            "shipped_at",
            "delivered_at",
            "history",
        ]

    def get_history(self, obj):
        return obj.status_history()


# PUBLIC_INTERFACE
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_items(request):
    """Admin-only: list all items or create a new item.

    GET: returns all items.
    POST: create item.
    """
    if request.method == "GET":
        qs = Item.objects.all().order_by("id")
        return Response(ItemSerializer(qs, many=True).data)

    serializer = ItemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return Response(ItemSerializer(item).data, status=status.HTTP_201_CREATED)


# PUBLIC_INTERFACE
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_item_detail(request, item_id: int):
    """Admin-only: retrieve/update/delete a single item."""
    item = get_object_or_404(Item, pk=item_id)

    if request.method == "GET":
        return Response(ItemSerializer(item).data)

    if request.method in ("PUT", "PATCH"):
        serializer = ItemSerializer(item, data=request.data, partial=(request.method == "PATCH"))
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(ItemSerializer(item).data)

    # DELETE
    item.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_inventory_adjust(request):
    """Admin-only: inventory adjustment endpoint (legacy compatibility).

    Applies stock delta to Item.stock_quantity atomically with row locking and prevents negative stock.

    Request:
        {"item_id": 123, "delta": -2}

    Response:
        {"item_id": 123, "stock_quantity": 10, "delta": -2}
    """
    payload = InventoryAdjustRequest(data=request.data)
    payload.is_valid(raise_exception=True)

    item_id = payload.validated_data["item_id"]
    delta = int(payload.validated_data["delta"])

    with transaction.atomic():
        item = get_object_or_404(Item.all_objects.select_for_update(), pk=item_id)
        next_qty = int(item.stock_quantity) + delta
        if next_qty < 0:
            return Response(
                {"detail": "Stock adjustment would result in negative stock.", "item_id": item.id},
                status=status.HTTP_400_BAD_REQUEST,
            )
        Item.all_objects.filter(pk=item.pk).update(stock_quantity=F("stock_quantity") + delta)
        item.refresh_from_db(fields=["stock_quantity"])
        return Response(
            {
                "item_id": item.id,
                "stock_quantity": item.stock_quantity,
                "delta": delta,
            },
            status=status.HTTP_200_OK,
        )


# PUBLIC_INTERFACE
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_orders(request):
    """Admin-only: list all orders (for operations)."""
    qs = Order.objects.all().order_by("-start_date")
    return Response(OrderAdminSerializer(qs, many=True).data)


# PUBLIC_INTERFACE
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_order_detail(request, order_id: int):
    """Admin-only: get an order with current status and history."""
    order = get_object_or_404(Order, pk=order_id)
    return Response(OrderAdminSerializer(order).data)


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_order_transition(request, order_id: int):
    """Admin-only: transition an order status.

    Valid transitions:
      placed -> shipped -> delivered

    Request:
      {"new_status": "shipped"}

    Response:
      Updated order (status + timestamps + legacy flags).
    """
    payload = OrderStatusTransitionRequest(data=request.data)
    payload.is_valid(raise_exception=True)

    new_status = payload.validated_data["new_status"]

    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        try:
            order.transition_to(new_status, actor=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        order.save()

    return Response(OrderAdminSerializer(order).data, status=status.HTTP_200_OK)


# PUBLIC_INTERFACE
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_my_orders(request):
    """User: list the authenticated user's paid orders with status and history."""
    qs = Order.objects.filter(user=request.user, ordered=True).order_by("-ordered_date")
    return Response(OrderMeSerializer(qs, many=True).data)


# PUBLIC_INTERFACE
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
