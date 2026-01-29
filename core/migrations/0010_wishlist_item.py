import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_payment_provider_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="WishlistItem",
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
                        related_name="wishlist_items",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="wishlistitem",
            constraint=models.UniqueConstraint(
                fields=("user", "item"), name="uniq_wishlist_user_item"
            ),
        ),
        migrations.AddIndex(
            model_name="wishlistitem",
            index=models.Index(fields=["user", "item"], name="idx_wishlist_user_item"),
        ),
        migrations.AddIndex(
            model_name="wishlistitem",
            index=models.Index(
                fields=["user", "created_at"], name="idx_wishlist_user_created"
            ),
        ),
    ]
