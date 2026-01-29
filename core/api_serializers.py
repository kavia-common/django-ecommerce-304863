"""
DRF serializers for the Core API.

We keep API serializers separate from API views to make it easier to evolve the API
surface independently of the storefront/template views.
"""

from __future__ import annotations

from rest_framework import serializers

from core.models import Item, WishlistItem


class ProductSerializer(serializers.ModelSerializer):
    """
    Product (Item) serializer for both public read and admin CRUD operations.

    Notes:
    - We expose inventory fields added in recent migrations.
    - `available_stock` is a computed read-only helper derived from model property.
    """

    available_stock = serializers.IntegerField(read_only=True)

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
            # Inventory/catalog enhancements
            "sku",
            "is_active",
            "low_stock_threshold",
            "stock_on_hand",
            "stock_reserved",
            "available_stock",
        ]
        read_only_fields = ["id", "available_stock"]


class WishlistItemSerializer(serializers.ModelSerializer):
    """
    Serializer for a user's wishlist entry.

    Exposes a denormalized item summary for convenient UI rendering.
    """

    item_id = serializers.IntegerField(source="item.id", read_only=True)
    title = serializers.CharField(source="item.title", read_only=True)
    price = serializers.FloatField(source="item.price", read_only=True)
    slug = serializers.SlugField(source="item.slug", read_only=True)
    available_stock = serializers.IntegerField(source="item.available_stock", read_only=True)
    image = serializers.ImageField(source="item.image", read_only=True)

    class Meta:
        model = WishlistItem
        fields = [
            "item_id",
            "title",
            "price",
            "slug",
            "available_stock",
            "image",
            "created_at",
        ]
        read_only_fields = fields


class WishlistAddSerializer(serializers.Serializer):
    """Input serializer for adding an item to a wishlist."""

    item_id = serializers.IntegerField()

    def validate_item_id(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("item_id must be a positive integer.")
        return value
