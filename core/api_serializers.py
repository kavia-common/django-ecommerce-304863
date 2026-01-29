"""
DRF serializers for the Core API.

We keep API serializers separate from API views to make it easier to evolve the API
surface independently of the storefront/template views.
"""

from __future__ import annotations

from rest_framework import serializers

from core.models import Item


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
