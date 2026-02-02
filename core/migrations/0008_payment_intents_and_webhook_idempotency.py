from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_order_lifecycle_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="stripe_charge_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="stripe_event_id",
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="stripe_payment_intent_client_secret",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="stripe_payment_intent_id",
            field=models.CharField(blank=True, db_index=True, max_length=128, null=True),
        ),
    ]
