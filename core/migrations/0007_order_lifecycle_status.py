from django.db import migrations, models
import django.utils.timezone


def forwards_fill_order_status(apps, schema_editor):
    Order = apps.get_model("core", "Order")
    now = django.utils.timezone.now()

    for order in Order.objects.all().iterator():
        # Ensure placed_at is set for paid orders
        placed_at = order.ordered_date if order.ordered_date else now
        shipped_at = getattr(order, "shipped_at", None)
        delivered_at = getattr(order, "delivered_at", None)

        if order.received:
            status = "delivered"
            if delivered_at is None:
                delivered_at = now
            if shipped_at is None:
                shipped_at = delivered_at
        elif order.being_delivered:
            status = "shipped"
            if shipped_at is None:
                shipped_at = now
        else:
            status = "placed"

        # Only set placed_at if order is actually ordered/paid; carts may exist too.
        if order.ordered and getattr(order, "placed_at", None) is None:
            order.placed_at = placed_at

        order.status = status
        order.shipped_at = shipped_at
        order.delivered_at = delivered_at
        order.save(update_fields=["status", "placed_at", "shipped_at", "delivered_at"])


def backwards_noop(apps, schema_editor):
    # We keep legacy boolean flags, so nothing required on reverse.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_item_inventory_stock"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[("placed", "Placed"), ("shipped", "Shipped"), ("delivered", "Delivered")],
                db_index=True,
                default="placed",
                help_text="Explicit order lifecycle status.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="placed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="shipped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(forwards_fill_order_status, backwards_noop),
    ]
