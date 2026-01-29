from django.db import migrations, models


def backfill_provider_reference(apps, schema_editor):
    Payment = apps.get_model("core", "Payment")
    for p in Payment.objects.all().only(
        "id", "stripe_charge_id", "provider_reference", "provider"
    ):
        if (not p.provider_reference) and p.stripe_charge_id:
            p.provider_reference = p.stripe_charge_id
        if not p.provider:
            p.provider = "stripe" if p.stripe_charge_id else "dummy"
        p.save(update_fields=["provider_reference", "provider"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_orderitem_inventory_tracking"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="stripe_charge_id",
            field=models.CharField(max_length=50, blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="provider",
            field=models.CharField(
                default="dummy",
                help_text="Payment provider name (e.g., stripe, dummy).",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="mode",
            field=models.CharField(
                default="dummy",
                help_text="Effective runtime mode used (dummy or stripe).",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="provider_reference",
            field=models.CharField(
                blank=True,
                help_text="Provider charge/intent identifier (id for idempotency/audit).",
                max_length=128,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="idempotency_key",
            field=models.CharField(
                default="",
                help_text="Idempotency key used to safely retry payment attempts.",
                max_length=128,
                unique=True,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("SUCCEEDED", "Succeeded"),
                    ("FAILED", "Failed"),
                ],
                db_index=True,
                default="PENDING",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="error_message",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="payment",
            name="raw_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(backfill_provider_reference, migrations.RunPython.noop),
    ]
