from __future__ import annotations

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from core.models import Item, Order
from core.rbac import ADMIN_GROUP_NAME, ensure_admin_group_exists


class Command(BaseCommand):
    help = "Create/ensure the Admin group exists and grant it elevated permissions."

    # PUBLIC_INTERFACE
    def handle(self, *args, **options):
        """Entrypoint for the setup_rbac management command."""
        group: Group = ensure_admin_group_exists()

        # Grant model-level permissions that correspond to "product management" and "order management".
        # Inventory adjustments are enforced at endpoint/view layer; the model does not include stock fields yet.
        models_to_grant = [Item, Order]

        perms_added = 0
        for model in models_to_grant:
            ct = ContentType.objects.get_for_model(model)
            for codename in ("add", "change", "delete", "view"):
                perm = Permission.objects.filter(
                    content_type=ct,
                    codename=f"{codename}_{model._meta.model_name}",
                ).first()
                if perm:
                    group.permissions.add(perm)
                    perms_added += 1

        self.stdout.write(self.style.SUCCESS(f"RBAC setup complete. Group='{ADMIN_GROUP_NAME}', perms_added={perms_added}"))
        self.stdout.write(
            "To grant a user admin role:\n"
            "  - in Django admin: Users -> <user> -> Groups -> add 'Admin'\n"
            "  - or via shell: user.groups.add(Group.objects.get(name='Admin'))"
        )
