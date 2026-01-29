import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_rbac_bootstrap_groups"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="sku",
            field=models.CharField(
                blank=True,
                help_text="Unique stock keeping unit. Nullable/blank for legacy items.",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Soft-enable/disable product without deleting it.",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="low_stock_threshold",
            field=models.IntegerField(
                default=0,
                help_text="Threshold at/below which the product should be considered low stock.",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="stock_on_hand",
            field=models.IntegerField(
                default=0,
                help_text="Physical stock currently on hand (available to allocate).",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="stock_reserved",
            field=models.IntegerField(
                default=0,
                help_text="Stock reserved for carts/orders not yet fulfilled.",
            ),
        ),
        migrations.CreateModel(
            name="InventoryAdjustment",
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
                    "delta",
                    models.IntegerField(
                        help_text="Signed quantity change (e.g. +10 received, -1 sale)."
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("RECEIVED", "Received"),
                            ("SALE", "Sale"),
                            ("RETURN", "Return"),
                            ("DAMAGE", "Damage"),
                            ("CORRECTION", "Correction"),
                            ("OTHER", "Other"),
                        ],
                        max_length=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("note", models.TextField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inventory_adjustments_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_adjustments",
                        to="core.Item",
                    ),
                ),
            ],
        ),
    ]
