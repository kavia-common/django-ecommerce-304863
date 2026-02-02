from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_review"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="coupon",
            name="code",
            field=models.CharField(db_index=True, max_length=40, unique=True),
        ),
        migrations.AlterField(
            model_name="coupon",
            name="amount",
            field=models.FloatField(
                default=0.0,
                help_text="Legacy fixed discount amount. Still supported for backward compatibility.",
                validators=[django.core.validators.MinValueValidator(0.0)],
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="discount_type",
            field=models.CharField(
                choices=[("fixed", "Fixed amount"), ("percent", "Percentage")],
                default="fixed",
                help_text="Fixed amount or percentage discount.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="percent_off",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Percentage off (0-100) when discount_type=percent.",
                max_digits=5,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="fixed_amount_off",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Fixed amount off when discount_type=fixed. If null, legacy `amount` is used.",
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="active",
            field=models.BooleanField(default=True, help_text="If false, coupon cannot be applied."),
        ),
        migrations.AddField(
            model_name="coupon",
            name="starts_at",
            field=models.DateTimeField(blank=True, help_text="Coupon valid from (inclusive).", null=True),
        ),
        migrations.AddField(
            model_name="coupon",
            name="ends_at",
            field=models.DateTimeField(blank=True, help_text="Coupon valid until (exclusive).", null=True),
        ),
        migrations.AddField(
            model_name="coupon",
            name="min_order_total",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Minimum order subtotal required to apply coupon.",
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="max_redemptions",
            field=models.PositiveIntegerField(
                blank=True, help_text="Global maximum successful redemptions (null = unlimited).", null=True
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="max_uses_per_user",
            field=models.PositiveIntegerField(
                blank=True, help_text="Maximum successful uses per user (null = unlimited).", null=True
            ),
        ),
        migrations.AddField(
            model_name="coupon",
            name="redemption_count",
            field=models.PositiveIntegerField(default=0, help_text="Successful uses count (maintained by system)."),
        ),
        migrations.AddField(
            model_name="coupon",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="coupon",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddIndex(
            model_name="coupon",
            index=models.Index(fields=["active", "starts_at", "ends_at"], name="core_coupon_active__f0df5e_idx"),
        ),
        migrations.CreateModel(
            name="CouponRedemption",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "coupon",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="redemptions",
                        to="core.coupon",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coupon_redemption",
                        to="core.order",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coupon_redemptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="couponredemption",
            constraint=models.UniqueConstraint(fields=("coupon", "order"), name="uniq_coupon_redemption_coupon_order"),
        ),
        migrations.AddIndex(
            model_name="couponredemption",
            index=models.Index(fields=["coupon", "created_at"], name="core_couponred_coupon_i_09f31f_idx"),
        ),
        migrations.AddIndex(
            model_name="couponredemption",
            index=models.Index(fields=["user", "created_at"], name="core_couponred_user_id_d4de2b_idx"),
        ),
        migrations.AddIndex(
            model_name="couponredemption",
            index=models.Index(fields=["coupon", "user", "created_at"], name="core_couponred_coupon__c0f141_idx"),
        ),
    ]
