import django.db.models.deletion
from django.db import migrations, models


def backfill_order_status(apps, schema_editor):
    Order = apps.get_model("core", "Order")
    # Backfill status based on legacy flags; keep it simple and deterministic.
    for order in Order.objects.all().iterator():
        if getattr(order, "refund_granted", False):
            status = "REFUNDED"
        elif getattr(order, "received", False):
            status = "DELIVERED"
        elif getattr(order, "being_delivered", False):
            status = "SHIPPED"
        elif getattr(order, "ordered", False):
            status = "PAID"
        else:
            status = "CREATED"
        if getattr(order, "status", None) != status:
            order.status = status
            order.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_catalog_inventory_enhancements"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("CREATED", "Created"),
                    ("PAID", "Paid"),
                    ("FULFILLING", "Fulfilling"),
                    ("SHIPPED", "Shipped"),
                    ("DELIVERED", "Delivered"),
                    ("CANCELLED", "Cancelled"),
                    ("REFUNDED", "Refunded"),
                ],
                db_index=True,
                default="CREATED",
                help_text="Explicit order lifecycle status.",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="OrderStatusHistory",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "from_status",
                    models.CharField(
                        choices=[
                            ("CREATED", "Created"),
                            ("PAID", "Paid"),
                            ("FULFILLING", "Fulfilling"),
                            ("SHIPPED", "Shipped"),
                            ("DELIVERED", "Delivered"),
                            ("CANCELLED", "Cancelled"),
                            ("REFUNDED", "Refunded"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            ("CREATED", "Created"),
                            ("PAID", "Paid"),
                            ("FULFILLING", "Fulfilling"),
                            ("SHIPPED", "Shipped"),
                            ("DELIVERED", "Delivered"),
                            ("CANCELLED", "Cancelled"),
                            ("REFUNDED", "Refunded"),
                        ],
                        max_length=16,
                    ),
                ),
                ("performed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "idempotency_key",
                    models.CharField(
                        blank=True,
                        help_text="Optional idempotency key to make transitions safe for retries.",
                        max_length=128,
                        null=True,
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_history",
                        to="core.Order",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="order_status_transitions",
                        to="auth.user",
                    ),
                ),
            ],
            options={"ordering": ["-performed_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="orderstatushistory",
            constraint=models.UniqueConstraint(
                condition=models.Q(("idempotency_key__isnull", False)),
                fields=("order", "idempotency_key"),
                name="uniq_order_transition_idempotency_key",
            ),
        ),
        migrations.RunPython(backfill_order_status, migrations.RunPython.noop),
    ]
