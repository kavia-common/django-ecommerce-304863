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
"""

from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from core.api_serializers import ProductSerializer
from core.models import Item
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
        """
        qs = super().get_queryset()

        # Restrict public list/retrieve to active products.
        # Note: retrieve() uses get_object() -> get_queryset(), so this also prevents
        # direct access to inactive items by id for anonymous/non-admin users.
        if self.action in ("list", "retrieve"):
            user = getattr(self.request, "user", None)
            is_adminish = bool(
                user
                and getattr(user, "is_authenticated", False)
                and (getattr(user, "is_superuser", False) or user.groups.filter(name="Admin").exists())
            )
            if not is_adminish:
                qs = qs.filter(is_active=True)

        return qs

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
