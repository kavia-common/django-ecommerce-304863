from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify
from django.core.validators import MinValueValidator


def forwards_populate_new_fields(apps, schema_editor):
    Item = apps.get_model("core", "Item")
    Category = apps.get_model("core", "Category")

    # Create Categories corresponding to legacy choices if they don't exist.
    legacy_map = {
        "S": ("Shirts", "shirts"),
        "SW": ("Sport wears", "sport-wears"),
        "OW": ("Outwears", "outwears"),
    }

    categories_by_code = {}
    for code, (name, slug) in legacy_map.items():
        cat, _ = Category.objects.get_or_create(slug=slug, defaults={"name": name, "active": True})
        categories_by_code[code] = cat

    # Backfill each item:
    # - sku: generate deterministic unique-ish SKU if missing
    # - primary_image: copy from legacy image if empty
    # - category_obj: map from legacy category choice
    for item in Item.objects.all().iterator():
        changed = False

        if not item.sku:
            # Deterministic SKU based on id and slug; ensure uniqueness with id.
            base = slugify(getattr(item, "slug", "") or getattr(item, "title", "") or "item")
            item.sku = f"SKU-{item.id}-{base}"[:64]
            changed = True

        if getattr(item, "primary_image", None) in (None, ""):
            try:
                item.primary_image = item.image
                changed = True
            except Exception:
                # If the legacy image isn't present/valid, keep it empty.
                pass

        if getattr(item, "category_obj_id", None) is None:
            cat = categories_by_code.get(item.category)
            if cat is not None:
                item.category_obj_id = cat.id
                changed = True

        if changed:
            item.save(update_fields=["sku", "primary_image", "category_obj"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_auto_20190630_1408"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(unique=True)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
                "verbose_name_plural": "Categories",
            },
        ),
        migrations.AddField(
            model_name="item",
            name="sku",
            field=models.CharField(
                max_length=64,
                unique=True,
                blank=True,
                help_text="Stock Keeping Unit (unique). Leave blank to auto-generate during migration.",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="item",
            name="primary_image",
            field=models.ImageField(blank=True, null=True, upload_to=""),
        ),
        migrations.AddField(
            model_name="item",
            name="gallery",
            field=models.JSONField(blank=True, null=True, default=list),
        ),
        migrations.AddField(
            model_name="item",
            name="category_obj",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="items",
                to="core.category",
                help_text="Optional structured category relation (preferred).",
            ),
        ),
        migrations.AddField(
            model_name="item",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="item",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(forwards_populate_new_fields, reverse_code=migrations.RunPython.noop),
        # Tighten non-null constraints on created_at/updated_at after backfill
        migrations.AlterField(
            model_name="item",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="item",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Add validation to existing numeric fields (model-level validators; DB not enforced for float)
        migrations.AlterField(
            model_name="item",
            name="price",
            field=models.FloatField(validators=[MinValueValidator(0.0)]),
        ),
        migrations.AlterField(
            model_name="item",
            name="discount_price",
            field=models.FloatField(blank=True, null=True, validators=[MinValueValidator(0.0)]),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(fields=["active", "created_at"], name="core_item_active_created_idx"),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(fields=["sku"], name="core_item_sku_idx"),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(fields=["slug"], name="core_item_slug_idx"),
        ),
    ]
