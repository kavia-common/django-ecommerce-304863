from django.db import migrations


def bootstrap_groups_and_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    admin_group, _ = Group.objects.get_or_create(name="Admin")
    Group.objects.get_or_create(name="User")

    # Assign model permissions commonly needed for admin endpoints.
    # Note: Django auto-creates add/change/delete/view permissions for models.
    desired_perm_codenames = [
        # Products (Item)
        "add_item",
        "change_item",
        "delete_item",
        "view_item",
        # Orders
        "change_order",
        "view_order",
        # Coupons
        "add_coupon",
        "change_coupon",
        "delete_coupon",
        "view_coupon",
        # Refund moderation
        "change_refund",
        "view_refund",
    ]

    perms = Permission.objects.filter(codename__in=desired_perm_codenames)
    if perms.exists():
        admin_group.permissions.add(*perms)


def remove_groups_permissions(apps, schema_editor):
    # Keep migration reversible but do not delete groups (might be used by real data).
    # We only remove permissions we added from the Admin group.
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    try:
        admin_group = Group.objects.get(name="Admin")
    except Group.DoesNotExist:
        return

    desired_perm_codenames = [
        "add_item",
        "change_item",
        "delete_item",
        "view_item",
        "change_order",
        "view_order",
        "add_coupon",
        "change_coupon",
        "delete_coupon",
        "view_coupon",
        "change_refund",
        "view_refund",
    ]
    perms = Permission.objects.filter(codename__in=desired_perm_codenames)
    if perms.exists():
        admin_group.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_auto_20190630_1408"),
        ("auth", "__latest__"),
    ]

    operations = [
        migrations.RunPython(bootstrap_groups_and_permissions, reverse_code=remove_groups_permissions),
    ]
