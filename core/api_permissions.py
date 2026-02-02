"""DRF permissions used by /api/** endpoints."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from .rbac import is_admin_user


class IsAdminRole(BasePermission):
    """Allow access only to Admin-role users.

    Admin-role is defined as:
    - Django superuser OR staff OR member of the "Admin" group
    """

    message = "Admin privileges are required to perform this action."

    def has_permission(self, request, view) -> bool:
        return is_admin_user(request)
