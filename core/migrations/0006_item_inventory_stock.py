from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_product_management_enhancements"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="track_inventory",
            field=models.BooleanField(
                default=True,
                help_text="If true, prevent purchase when stock_quantity is insufficient.",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="stock_quantity",
            field=models.IntegerField(
                default=0,
                validators=[MinValueValidator(0)],
                help_text="Available stock on hand (non-negative).",
            ),
        ),
    ]
