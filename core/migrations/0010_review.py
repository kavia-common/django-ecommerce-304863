from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_wishlist_entry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Review",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "rating",
                    models.PositiveSmallIntegerField(
                        help_text="Rating from 1 to 5.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=200, null=True)),
                ("body", models.TextField(help_text="Review text.")),
                (
                    "is_hidden",
                    models.BooleanField(
                        default=False,
                        help_text="If true, this review is hidden from public display (moderation).",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="core.item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.UniqueConstraint(fields=("user", "item"), name="uniq_review_user_item"),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(fields=["item", "created_at"], name="core_review_item_id_0f5c30_idx"),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(fields=["user", "created_at"], name="core_review_user_id_c5a2d3_idx"),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(fields=["item", "is_hidden", "created_at"], name="core_review_item_id_9ddf33_idx"),
        ),
    ]
