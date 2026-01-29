"""
DRF viewsets for the Core API.

Requirements implemented:
- Public read-only endpoints:
  - GET /api/products/
  - GET /api/products/{id}/
- Admin-only endpoints on the same resource:
  - POST/PUT/PATCH/DELETE /api/products/...
  Guarded by existing RBAC: Admin group / Django permissions (see core.permissions)

Additional behavior:
- Public list is filtered to active products by default.
- Search/filter on title and SKU.
- Ordering by price/title.

Wishlist:
- JWT-protected endpoints:
  - GET /api/wishlist/
  - POST /api/wishlist/ {"item_id": <id>}
  - DELETE /api/wishlist/{item_id}/
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ViewSet

from core.api_serializers import (
    ProductSerializer,
    ReviewPublicSerializer,
    WishlistAddSerializer,
    WishlistItemSerializer,
)
from core.models import Item, Review, WishlistItem
from core.permissions import IsAdminGroupOrDjangoPermission


class ProductViewSet(ModelViewSet):
    """
    ViewSet for Item/Product.

    Public:
      - list/retrieve allowed without auth (AllowAny)
      - list/retrieve are restricted to active products (`is_active=True`)

    Admin:
      - create/update/partial_update/destroy require authenticated admin RBAC

    Search / ordering:
      - Search by title and sku (case-insensitive)
      - Ordering by price/title (also supports -price, -title)

    Reviews:
      - Exposes aggregate stats (average_rating, review_count) derived from approved reviews.
      - Nested endpoint:
          GET /api/products/{id}/reviews/  (approved-only, read-only)
    """

    serializer_class = ProductSerializer
    queryset = Item.objects.all()

    # DRF filter backends (activated globally or per-view; we declare here explicitly)
    filterset_fields = ["is_active", "sku", "category", "label"]
    search_fields = ["title", "sku"]
    ordering_fields = ["price", "title"]
    ordering = ["id"]

    def get_queryset(self):
        """
        Apply default filtering rules.

        For public requests (no auth required), we only show active products for
        list/retrieve actions. Admins can see all products by default.

        Also annotates approved review aggregates to avoid N+1 on list endpoints.
        """
        qs = super().get_queryset()

        qs = qs.annotate(
            average_rating=Avg("reviews__rating", filter=Q(reviews__is_approved=True)),
            review_count=Count(
                "reviews__id", filter=Q(reviews__is_approved=True), distinct=True
            ),
        )

        # Restrict public list/retrieve to active products.
        # Note: retrieve() uses get_object() -> get_queryset(), so this also prevents
        # direct access to inactive items by id for anonymous/non-admin users.
        if self.action in ("list", "retrieve", "reviews"):
            user = getattr(self.request, "user", None)
            is_adminish = bool(
                user
                and getattr(user, "is_authenticated", False)
                and (
                    getattr(user, "is_superuser", False)
                    or user.groups.filter(name="Admin").exists()
                )
            )
            if not is_adminish:
                qs = qs.filter(is_active=True)

        return qs

    # PUBLIC_INTERFACE
    @action(
        detail=True,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="reviews",
    )
    def reviews(self, request, pk=None):
        """
        List approved reviews for a specific product.

        Route:
          GET /api/products/{id}/reviews/

        Notes:
          - Only approved reviews are returned.
          - This is public read-only.
        """
        item = self.get_object()
        qs = (
            Review.objects.filter(item=item, is_approved=True)
            .select_related("user", "item")
            .order_by("-created_at", "-id")
        )

        # Basic DRF pagination support.
        page = getattr(self, "paginator", None)
        if page is None:
            from rest_framework.pagination import PageNumberPagination

            self.paginator = PageNumberPagination()
            page = self.paginator

        paged = page.paginate_queryset(qs, request, view=self)
        serializer = ReviewPublicSerializer(paged if paged is not None else qs, many=True)
        if paged is not None:
            return page.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def get_permissions(self):
        """
        Public read-only, admin-only write.

        We intentionally keep the same route for public + admin, switching permissions
        based on action.
        """
        if self.action in ("list", "retrieve"):
            return [AllowAny()]

        # For write actions, require auth + RBAC permission class
        # (Admin group OR relevant Django model perms).
        return [IsAuthenticated(), IsAdminGroupOrDjangoPermission()]

    # Attribute consumed by IsAdminGroupOrDjangoPermission
    required_django_perms = (
        "core.add_item",
        "core.change_item",
        "core.delete_item",
        "core.view_item",
    )


class WishlistViewSet(ViewSet):
    """
    Wishlist endpoints for the current authenticated user.

    Routes (mounted via DefaultRouter):
      - GET    /api/wishlist/               list
      - POST   /api/wishlist/               create   body: {"item_id": <id>}
      - DELETE /api/wishlist/{item_id}/     destroy  (idempotent)

    Notes:
      - This API is *user-scoped*: users can only see/mutate their own wishlist.
      - create is idempotent: if the item is already wishlisted, returns 200 OK.
      - destroy is idempotent: removing a non-existent entry returns 204 No Content.
    """

    permission_classes = [IsAuthenticated]

    def _base_queryset(self):
        """
        Base queryset scoped to the current user, optimized for list rendering.
        """
        return (
            WishlistItem.objects.filter(user=self.request.user)
            .select_related("item")
            .order_by("-created_at", "-id")
        )

    # PUBLIC_INTERFACE
    def list(self, request):
        """List the current user's wishlist items (paginated)."""
        qs = self._base_queryset()

        # Use DRF paginator from generic API stack without converting to GenericViewSet
        # (we keep this ViewSet minimal but still paginated).
        page = getattr(self, "paginator", None)
        if page is None:
            # Lazy-init paginator using DRF's default pagination class (if configured).
            from rest_framework.pagination import PageNumberPagination

            self.paginator = PageNumberPagination()
            page = self.paginator

        paged = page.paginate_queryset(qs, request, view=self)
        serializer = WishlistItemSerializer(paged if paged is not None else qs, many=True)
        if paged is not None:
            return page.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # PUBLIC_INTERFACE
    def create(self, request):
        """Add an item to the current user's wishlist (idempotent)."""
        input_serializer = WishlistAddSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        item_id = input_serializer.validated_data["item_id"]

        # Ensure item exists (404 if not).
        item = Item.objects.filter(pk=item_id).first()
        if not item:
            return Response({"detail": "Item not found."}, status=status.HTTP_404_NOT_FOUND)

        # Idempotent insert; safe under concurrency.
        try:
            with transaction.atomic():
                obj, created = WishlistItem.objects.get_or_create(
                    user=request.user, item=item
                )
        except IntegrityError:
            # In case of race, fetch the existing record.
            obj = WishlistItem.objects.get(user=request.user, item=item)
            created = False

        payload = WishlistItemSerializer(obj).data
        return Response(
            payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    # PUBLIC_INTERFACE
    def destroy(self, request, pk=None):
        """
        Remove an item from the current user's wishlist (idempotent).

        Router passes {pk}; we mount this as /api/wishlist/{item_id}/
        """
        try:
            item_id = int(pk)
        except (TypeError, ValueError):
            return Response({"detail": "Invalid item id."}, status=status.HTTP_400_BAD_REQUEST)

        WishlistItem.objects.filter(user=request.user, item_id=item_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
