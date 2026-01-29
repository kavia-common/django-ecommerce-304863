"""
DRF serializers for the Core API.

We keep API serializers separate from API views to make it easier to evolve the API
surface independently of the storefront/template views.
"""

from __future__ import annotations

from django.db.models import Avg, Count
from rest_framework import serializers

from core.models import Item, Review, WishlistItem


class ProductSerializer(serializers.ModelSerializer):
    """
    Product (Item) serializer for both public read and admin CRUD operations.

    Notes:
    - We expose inventory fields added in recent migrations.
    - `available_stock` is a computed read-only helper derived from model property.
    - Reviews: we expose aggregate stats computed from APPROVED reviews only.
    """

    available_stock = serializers.IntegerField(read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    review_count = serializers.IntegerField(read_only=True)

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
            # Review aggregates (approved only)
            "average_rating",
            "review_count",
        ]
        read_only_fields = ["id", "available_stock", "average_rating", "review_count"]

    def to_representation(self, instance):
        """
        Compute review aggregates in one query per item unless viewset annotates.

        Viewsets should annotate these fields for list endpoints to avoid N+1; this
        method is a safe fallback for single-item usage.
        """
        data = super().to_representation(instance)

        # If annotated already, respect it.
        if data.get("average_rating") is not None and data.get("review_count") is not None:
            return data

        agg = (
            Review.objects.filter(item=instance, is_approved=True)
            .aggregate(avg=Avg("rating"), cnt=Count("id"))
        )
        avg = agg.get("avg")
        cnt = agg.get("cnt") or 0
        data["average_rating"] = float(avg) if avg is not None else None
        data["review_count"] = int(cnt)
        return data


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


class ReviewPublicSerializer(serializers.ModelSerializer):
    """
    Public read-only serializer for approved reviews.

    We intentionally expose minimal user identity fields.
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    item_id = serializers.IntegerField(source="item.id", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "item_id",
            "user_id",
            "username",
            "rating",
            "title",
            "body",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReviewWriteSerializer(serializers.ModelSerializer):
    """
    Create/update serializer for a user's own review.

    Important behavior:
      - user is set from request.user (not user-supplied).
      - item is set from item_id.
      - users cannot set is_approved; moderation only.
    """

    item_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "item_id",
            "rating",
            "title",
            "body",
            "is_approved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_approved", "created_at", "updated_at"]

    def validate_item_id(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("item_id must be a positive integer.")
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        item_id = validated_data.pop("item_id")

        item = Item.objects.filter(pk=item_id).first()
        if not item:
            raise serializers.ValidationError({"item_id": "Item not found."})

        # New reviews always require moderation.
        review = Review.objects.create(user=user, item=item, is_approved=False, **validated_data)
        return review

    def update(self, instance, validated_data):
        # item_id is not editable for existing reviews.
        validated_data.pop("item_id", None)

        for field in ("rating", "title", "body"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        instance.save()
        return instance


class ReviewAdminSerializer(serializers.ModelSerializer):
    """
    Admin serializer exposing moderation fields.
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    item_id = serializers.IntegerField(source="item.id", read_only=True)
    item_title = serializers.CharField(source="item.title", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "item_id",
            "item_title",
            "user_id",
            "username",
            "rating",
            "title",
            "body",
            "is_approved",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "item_id", "item_title", "user_id", "username"]


class ReviewModerationSerializer(serializers.Serializer):
    """Payload for moderation actions such as approve/reject."""

    is_approved = serializers.BooleanField()
