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
    """Request payload for inventory adjustments.

    Note: The current data model does not have stock quantities. We provide a safe
    placeholder endpoint that can be extended once inventory fields are introduced.
    """

    item_id = serializers.IntegerField(help_text="Item ID to adjust.")
    delta = serializers.IntegerField(help_text="Stock delta (positive or negative).")


class OrderStatusTransitionRequest(serializers.Serializer):
    """Request payload for order status transitions (admin-only).

    The current Order model uses boolean flags:
    - being_delivered
    - received
    - refund_granted
    - refund_requested
    """

    being_delivered = serializers.BooleanField(required=False)
    received = serializers.BooleanField(required=False)
    refund_granted = serializers.BooleanField(required=False)


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
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_order_transition(request, order_id: int):
    """Admin-only: transition an order status.

    Updates boolean flags on Order safely inside a transaction.
    """
    payload = OrderStatusTransitionRequest(data=request.data)
    payload.is_valid(raise_exception=True)

    order = get_object_or_404(Order, pk=order_id)

    with transaction.atomic():
        data = payload.validated_data
        # Apply only provided fields
        if "being_delivered" in data:
            order.being_delivered = data["being_delivered"]
        if "received" in data:
            order.received = data["received"]
        if "refund_granted" in data:
            order.refund_granted = data["refund_granted"]
        order.save()

    return Response(
        {
            "id": order.id,
            "being_delivered": order.being_delivered,
            "received": order.received,
            "refund_requested": order.refund_requested,
            "refund_granted": order.refund_granted,
        }
    )
