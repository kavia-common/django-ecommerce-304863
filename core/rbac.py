"""RBAC helpers for the application.

We use Django Groups for role management:
- Regular users: not in the Admin group
- Admin users: members of the "Admin" group (or Django staff/superuser)

This module is intentionally small and reusable across:
- DRF API permissions
- Template view decorators/mixins
"""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.http import HttpRequest

ADMIN_GROUP_NAME = "Admin"


def _safe_user(request_or_user):
    """Return a user instance from either a request or a user object."""
    if hasattr(request_or_user, "user"):
        return request_or_user.user
    return request_or_user


# PUBLIC_INTERFACE
def is_admin_user(request_or_user) -> bool:
    """Return True if the given user (or request.user) should be treated as Admin.

    A user is Admin if:
    - they are authenticated AND
    - they are a superuser OR staff OR belong to the Admin group
    """
    user = _safe_user(request_or_user)
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True

    return user.groups.filter(name=ADMIN_GROUP_NAME).exists()


# PUBLIC_INTERFACE
def ensure_admin_group_exists() -> Group:
    """Create the Admin group if missing and return it."""
    group, _ = Group.objects.get_or_create(name=ADMIN_GROUP_NAME)
    return group


# PUBLIC_INTERFACE
def request_is_admin(request: HttpRequest) -> bool:
    """Convenience helper for decorators expecting `request`."""
    return is_admin_user(request)
