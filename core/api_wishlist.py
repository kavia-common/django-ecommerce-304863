"""Wishlist API endpoints (authenticated users).

Endpoints:
- GET  /api/wishlist/            -> list current user's wishlist items
- POST /api/wishlist/add/        -> add an item to wishlist (no duplicates)
- POST /api/wishlist/remove/     -> remove an item from wishlist (idempotent)

These endpoints are intended for regular authenticated users (no admin-only constraint).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Item, WishlistEntry


class WishlistItemSerializer(serializers.ModelSerializer):
    """Serializer for Item returned in wishlist listing."""

    class Meta:
        model = Item
        fields = [
            "id",
            "title",
            "price",
            "discount_price",
            "slug",
            "description",
            "image",
            "primary_image",
        ]


class WishlistAddRemoveRequest(serializers.Serializer):
    """Request payload for add/remove actions."""

    item_id = serializers.IntegerField(help_text="Item ID to add/remove from wishlist.")


# PUBLIC_INTERFACE
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_wishlist_list(request):
    """List wishlist items for the authenticated user.

    Returns:
        200 OK: {"count": <int>, "items": [<Item>, ...]}
    """
    qs = (
        WishlistEntry.objects.filter(user=request.user)
        .select_related("item")
        .order_by("-created_at", "id")
    )
    items = [e.item for e in qs]
    return Response(
        {"count": len(items), "items": WishlistItemSerializer(items, many=True).data},
        status=status.HTTP_200_OK,
    )


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_wishlist_add(request):
    """Add an item to the authenticated user's wishlist (no duplicates).

    Request:
        {"item_id": 123}

    Responses:
        201 Created: {"detail": "Added", "item_id": 123}
        200 OK: {"detail": "Already in wishlist", "item_id": 123}   (duplicate add is safe)
        404 Not Found: if item does not exist
    """
    payload = WishlistAddRemoveRequest(data=request.data)
    payload.is_valid(raise_exception=True)
    item = get_object_or_404(Item, pk=payload.validated_data["item_id"])

    # Enforce no duplicates via unique constraint; treat duplicates as success.
    try:
        with transaction.atomic():
            WishlistEntry.objects.create(user=request.user, item=item)
        return Response({"detail": "Added", "item_id": item.id}, status=status.HTTP_201_CREATED)
    except IntegrityError:
        return Response({"detail": "Already in wishlist", "item_id": item.id}, status=status.HTTP_200_OK)


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_wishlist_remove(request):
    """Remove an item from the authenticated user's wishlist.

    Request:
        {"item_id": 123}

    Response:
        200 OK: {"detail": "Removed", "item_id": 123} (idempotent: still OK if not present)
    """
    payload = WishlistAddRemoveRequest(data=request.data)
    payload.is_valid(raise_exception=True)
    item_id = payload.validated_data["item_id"]

    WishlistEntry.objects.filter(user=request.user, item_id=item_id).delete()
    return Response({"detail": "Removed", "item_id": item_id}, status=status.HTTP_200_OK)
