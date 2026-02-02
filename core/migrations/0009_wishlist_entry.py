from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_payment_intents_and_webhook_idempotency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WishlistEntry",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wishlisted_by",
                        to="core.item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wishlist_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="wishlistentry",
            constraint=models.UniqueConstraint(fields=("user", "item"), name="uniq_wishlist_user_item"),
        ),
        migrations.AddIndex(
            model_name="wishlistentry",
            index=models.Index(fields=["user", "created_at"], name="core_wishli_user_id_7c4b7d_idx"),
        ),
        migrations.AddIndex(
            model_name="wishlistentry",
            index=models.Index(fields=["item"], name="core_wishli_item_id_9b4e2f_idx"),
        ),
    ]
