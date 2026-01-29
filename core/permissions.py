"""
DRF permission utilities for the core API.

We implement RBAC using Django's built-in Groups/Permissions system:
- "Admin" group: allowed to access admin-only endpoints.
- "User" group: baseline group for authenticated customers (optional).
"""

from __future__ import annotations

from typing import Iterable, Optional

from django.contrib.auth.models import AnonymousUser
from rest_framework.permissions import BasePermission


def _is_authenticated(user) -> bool:
    return bool(
        user
        and not isinstance(user, AnonymousUser)
        and getattr(user, "is_authenticated", False)
    )


def _in_group(user, group_name: str) -> bool:
    if not _is_authenticated(user):
        return False
    return user.groups.filter(name=group_name).exists()


def _has_any_perm(user, perms: Iterable[str]) -> bool:
    if not _is_authenticated(user):
        return False
    for perm in perms:
        if user.has_perm(perm):
            return True
    return False


class IsAdminGroupOrSuperuser(BasePermission):
    """
    Allows access only to:
    - superusers, OR
    - members of the 'Admin' group.
    """

    message = "Admin access required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not _is_authenticated(user):
            return False
        return bool(user.is_superuser or _in_group(user, "Admin"))


class IsAdminGroupOrDjangoPermission(BasePermission):
    """
    Allows access only to:
    - superusers, OR
    - members of the 'Admin' group, OR
    - users having at least one of the configured Django model permissions.

    Views using this should define `required_django_perms` as an iterable of permission codenames:
        required_django_perms = ("core.add_item", "core.change_item", ...)
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not _is_authenticated(user):
            return False
        if user.is_superuser or _in_group(user, "Admin"):
            return True

        perms: Optional[Iterable[str]] = getattr(view, "required_django_perms", None)
        if not perms:
            # If a view forgets to specify perms, default to deny (safer).
            return False
        return _has_any_perm(user, perms)
