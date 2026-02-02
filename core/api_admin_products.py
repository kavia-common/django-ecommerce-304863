"""Admin/staff product management API endpoints.

These endpoints live under /api/admin/products/** and are intended for internal tooling.
They do not affect server-rendered storefront routes.

RBAC:
- Requires JWT authentication
- Requires IsAdminRole permission (Admin group OR staff OR superuser)

Image handling:
- Endpoints accept standard DRF request.data; file uploads require multipart/form-data.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api_permissions import IsAdminRole
from .models import Category, Item


class CategorySerializer(serializers.ModelSerializer):
    """Serializer for Category CRUD."""
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "active", "created_at", "updated_at"]


class ItemAdminSerializer(serializers.ModelSerializer):
    """Serializer for admin CRUD of items.

    Notes:
    - Uses Item.all_objects to include inactive products.
    - Enforces price/discount_price non-negative via model validators.
    - Enforces SKU uniqueness via model field unique constraint + DRF validation.
    """

    category = serializers.ChoiceField(choices=Item._meta.get_field("category").choices)
    category_obj_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "title",
            "sku",
            "active",
            "price",
            "discount_price",
            "category",
            "category_obj_id",
            "label",
            "slug",
            "description",
            "image",
            "primary_image",
            "gallery",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_discount_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("discount_price must be non-negative.")
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("price must be non-negative.")
        return value

    def validate(self, attrs):
        # Ensure discount <= price when both provided (common-sense validation)
        price = attrs.get("price", getattr(self.instance, "price", None))
        discount = attrs.get("discount_price", getattr(self.instance, "discount_price", None))
        if price is not None and discount is not None and discount > price:
            raise serializers.ValidationError({"discount_price": "discount_price cannot exceed price."})
        return attrs

    def create(self, validated_data):
        category_obj_id = validated_data.pop("category_obj_id", None)
        if category_obj_id is not None:
            validated_data["category_obj"] = get_object_or_404(Category, pk=category_obj_id)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        category_obj_id = validated_data.pop("category_obj_id", None)
        if category_obj_id is not None:
            if category_obj_id is None:
                instance.category_obj = None
            else:
                instance.category_obj = get_object_or_404(Category, pk=category_obj_id)
        return super().update(instance, validated_data)


# PUBLIC_INTERFACE
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_product_categories(request):
    """Admin-only: list or create categories.

    GET: list all categories (including inactive).
    POST: create a category.
    """
    if request.method == "GET":
        qs = Category.objects.all().order_by("name")
        return Response(CategorySerializer(qs, many=True).data)

    serializer = CategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    cat = serializer.save()
    return Response(CategorySerializer(cat).data, status=status.HTTP_201_CREATED)


# PUBLIC_INTERFACE
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_product_category_detail(request, category_id: int):
    """Admin-only: retrieve/update/delete a category."""
    cat = get_object_or_404(Category, pk=category_id)

    if request.method == "GET":
        return Response(CategorySerializer(cat).data)

    if request.method in ("PUT", "PATCH"):
        serializer = CategorySerializer(cat, data=request.data, partial=(request.method == "PATCH"))
        serializer.is_valid(raise_exception=True)
        cat = serializer.save()
        return Response(CategorySerializer(cat).data)

    cat.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# PUBLIC_INTERFACE
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_product_items(request):
    """Admin-only: list or create items (including inactive).

    GET: list all items.
    POST: create item.
    """
    if request.method == "GET":
        qs = Item.all_objects.all().order_by("-created_at", "id")
        return Response(ItemAdminSerializer(qs, many=True).data)

    serializer = ItemAdminSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return Response(ItemAdminSerializer(item).data, status=status.HTTP_201_CREATED)


# PUBLIC_INTERFACE
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_product_item_detail(request, item_id: int):
    """Admin-only: retrieve/update/delete a single item (including inactive).

    Use PATCH to deactivate by setting {"active": false} without deleting.
    """
    item = get_object_or_404(Item.all_objects.all(), pk=item_id)

    if request.method == "GET":
        return Response(ItemAdminSerializer(item).data)

    if request.method in ("PUT", "PATCH"):
        serializer = ItemAdminSerializer(item, data=request.data, partial=(request.method == "PATCH"))
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(ItemAdminSerializer(item).data)

    item.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_product_item_deactivate(request, item_id: int):
    """Admin-only: deactivate an item (soft-hide from storefront)."""
    item = get_object_or_404(Item.all_objects.all(), pk=item_id)
    with transaction.atomic():
        item.active = False
        item.save(update_fields=["active", "updated_at"])
    return Response({"id": item.id, "active": item.active})
