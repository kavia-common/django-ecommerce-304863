from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_order_lifecycle_status_and_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="quantity_reserved",
            field=models.IntegerField(
                default=0,
                help_text="Units reserved on the Item for this OrderItem (not yet paid/fulfilled).",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="quantity_committed",
            field=models.IntegerField(
                default=0,
                help_text="Units committed (sold) for this OrderItem after payment success.",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="quantity_restocked",
            field=models.IntegerField(
                default=0,
                help_text="Units restocked back to on-hand due to refunds/returns.",
            ),
        ),
    ]
