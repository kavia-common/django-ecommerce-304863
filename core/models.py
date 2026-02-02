from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import post_save
from django.shortcuts import reverse
from django.utils import timezone
from django_countries.fields import CountryField

CATEGORY_CHOICES = (
    ("S", "Shirt"),
    ("SW", "Sport wear"),
    ("OW", "Outwear"),
)

LABEL_CHOICES = (
    ("P", "primary"),
    ("S", "secondary"),
    ("D", "danger"),
)

ADDRESS_CHOICES = (
    ("B", "Billing"),
    ("S", "Shipping"),
)


def _to_decimal_money(value) -> Decimal:
    """Convert value to Decimal money with 2dp, safe for floats/None."""
    if value is None:
        return Decimal("0.00")
    try:
        d = Decimal(str(value))
    except Exception:
        d = Decimal("0.00")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stripe_customer_id = models.CharField(max_length=50, blank=True, null=True)
    one_click_purchasing = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


class CategoryQuerySet(models.QuerySet):
    """QuerySet for Category with convenience filters."""

    def active(self):
        """Return only active categories."""
        return self.filter(active=True)


class Category(models.Model):
    """Product category suitable for merchandising and filtering."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CategoryQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class ItemQuerySet(models.QuerySet):
    """QuerySet for Item with storefront-safe defaults."""

    def active(self):
        """Return only active items."""
        return self.filter(active=True)


class ActiveItemManager(models.Manager):
    """Manager that returns only active items.

    Used by default for storefront queries to ensure inactive products are hidden.
    """

    def get_queryset(self):
        return super().get_queryset().filter(active=True)


class Item(models.Model):
    # Keep existing fields to avoid breaking templates/checkout/cart flows.
    title = models.CharField(max_length=100)

    price = models.FloatField(validators=[MinValueValidator(0.0)])
    discount_price = models.FloatField(blank=True, null=True, validators=[MinValueValidator(0.0)])

    # Legacy category choice (kept for backward compatibility with templates and existing data)
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=2)

    # New category relation (production-ready)
    category_obj = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="items",
        help_text="Optional structured category relation (preferred).",
    )

    label = models.CharField(choices=LABEL_CHOICES, max_length=1)
    slug = models.SlugField()

    # New merchandising/product management fields
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        help_text="Stock Keeping Unit (unique). Leave blank to auto-generate during migration.",
    )
    active = models.BooleanField(default=True)

    # Inventory fields
    track_inventory = models.BooleanField(
        default=True,
        help_text="If true, prevent purchase when stock_quantity is insufficient.",
    )
    stock_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Available stock on hand (non-negative).",
    )

    description = models.TextField()

    # Legacy image field (kept) + new primary_image field (preferred).
    image = models.ImageField()
    primary_image = models.ImageField(blank=True, null=True)

    # Simple optional gallery as JSON list of image paths/URLs.
    # Using JSONField avoids adding new tables while allowing future enhancements.
    try:
        from django.db.models import JSONField  # Django 3.1+

        gallery = JSONField(blank=True, null=True, default=list)
    except Exception:  # pragma: no cover
        # Fallback for older Django; project appears modern enough but keep safe.
        gallery = models.TextField(blank=True, null=True, help_text="JSON-encoded list of images.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Storefront should default to active items only.
    objects = ActiveItemManager()
    # Admin/ops queries can use all_objects to include inactive items.
    all_objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["active", "created_at"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.title

    def is_in_stock(self) -> bool:
        """Return whether this item is available for purchase."""
        if not self.track_inventory:
            return True
        return self.stock_quantity > 0

    def available_stock(self) -> int:
        """Return available stock quantity (0 if not tracking inventory)."""
        if not self.track_inventory:
            return 10**9
        return int(self.stock_quantity)

    # PUBLIC_INTERFACE
    def ensure_can_fulfill(self, requested_qty: int) -> None:
        """Validate that requested quantity can be fulfilled.

        Raises:
            ValueError: if requested_qty is invalid or exceeds available stock.
        """
        if requested_qty is None or int(requested_qty) <= 0:
            raise ValueError("requested_qty must be a positive integer.")
        if self.track_inventory and int(requested_qty) > int(self.stock_quantity):
            raise ValueError(f"Insufficient stock for '{self.title}'. Available: {self.stock_quantity}.")

    # PUBLIC_INTERFACE
    @classmethod
    def atomic_decrement_stock_for_order(cls, order: "Order") -> None:
        """Atomically decrement stock for all items in an order.

        This method prevents oversell by:
        - locking the relevant Item rows (SELECT ... FOR UPDATE)
        - validating each ordered quantity against current stock
        - applying decrements with F() expressions inside a transaction

        Args:
            order: The Order (must be the not-yet-ordered cart being finalized).

        Raises:
            ValueError: if stock is insufficient for any item in the order.
        """
        # IMPORTANT: Must be called inside an outer transaction.atomic() block.
        order_items = list(order.items.select_related("item").all())
        item_ids = [oi.item_id for oi in order_items]

        # Lock all involved Item rows deterministically to avoid deadlocks.
        locked_items = (
            cls.all_objects.select_for_update()
            .filter(id__in=item_ids)
            .order_by("id")
        )
        items_by_id = {it.id: it for it in locked_items}

        # Validate and apply decrements.
        for oi in order_items:
            item = items_by_id[oi.item_id]
            if not item.track_inventory:
                continue
            if oi.quantity > item.stock_quantity:
                raise ValueError(
                    f"Insufficient stock for '{item.title}'. Requested: {oi.quantity}, Available: {item.stock_quantity}."
                )

        for oi in order_items:
            item = items_by_id[oi.item_id]
            if not item.track_inventory:
                continue
            # Use F() to avoid race conditions.
            cls.all_objects.filter(pk=item.pk).update(
                stock_quantity=F("stock_quantity") - int(oi.quantity),
                updated_at=timezone.now(),
            )

    def get_absolute_url(self):
        return reverse(
            "core:product",
            kwargs={
                "slug": self.slug,
            },
        )

    def get_add_to_cart_url(self):
        return reverse(
            "core:add-to-cart",
            kwargs={
                "slug": self.slug,
            },
        )

    def get_remove_from_cart_url(self):
        return reverse(
            "core:remove-from-cart",
            kwargs={
                "slug": self.slug,
            },
        )

    def get_storefront_image(self):
        """Return best-available image for storefront display (template-safe)."""
        if self.primary_image:
            return self.primary_image
        return self.image

    # PUBLIC_INTERFACE
    def average_rating(self) -> float:
        """Return average rating for this item (visible reviews only).

        Returns:
            float: average rating (0.0 if no ratings).
        """
        agg = self.reviews.filter(is_hidden=False).aggregate(avg=models.Avg("rating"))
        val = agg.get("avg")
        return float(val) if val is not None else 0.0

    # PUBLIC_INTERFACE
    def reviews_count(self) -> int:
        """Return count of visible reviews for this item."""
        return int(self.reviews.filter(is_hidden=False).count())

    # PUBLIC_INTERFACE
    def rating_distribution(self) -> dict:
        """Return rating distribution for visible reviews.

        Returns:
            dict: keys 1..5 -> count
        """
        from django.db.models import Count

        dist = {i: 0 for i in range(1, 6)}
        rows = self.reviews.filter(is_hidden=False).values("rating").annotate(c=Count("id"))
        for r in rows:
            dist[int(r["rating"])] = int(r["c"])
        return dist


class WishlistEntry(models.Model):
    """Wishlist entry connecting a user to an Item.

    We use an explicit through model instead of a ManyToManyField to:
    - enforce uniqueness (no duplicate wishlist rows)
    - support future metadata (added_at, notes, etc.)
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishlist_entries",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="wishlisted_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "item"], name="uniq_wishlist_user_item"),
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["item"]),
        ]
        ordering = ["-created_at", "id"]

    def __str__(self):
        return f"{self.user_id}:{self.item_id}"


class OrderItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ordered = models.BooleanField(default=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} of {self.item.title}"

    def get_total_item_price(self):
        return self.quantity * self.item.price

    def get_total_discount_item_price(self):
        return self.quantity * self.item.discount_price

    def get_amount_saved(self):
        return self.get_total_item_price() - self.get_total_discount_item_price()

    def get_final_price(self):
        if self.item.discount_price:
            return self.get_total_discount_item_price()
        return self.get_total_item_price()


class Coupon(models.Model):
    """Coupon/discount code.

    Backward compatibility:
      - Older data uses `amount` as a fixed discount value.
      - New fields support fixed/percentage discounts + rules/limits.
    """

    class DiscountType(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percentage"

    code = models.CharField(max_length=40, unique=True, db_index=True)

    # Legacy fixed discount (kept). When discount_type is FIXED and amount is set, it is used.
    amount = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0)],
        help_text="Legacy fixed discount amount. Still supported for backward compatibility.",
    )

    discount_type = models.CharField(
        max_length=10,
        choices=DiscountType.choices,
        default=DiscountType.FIXED,
        help_text="Fixed amount or percentage discount.",
    )

    # For percent: 0..100. For fixed: can be left null to use legacy `amount`.
    percent_off = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Percentage off (0-100) when discount_type=percent.",
    )
    fixed_amount_off = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Fixed amount off when discount_type=fixed. If null, legacy `amount` is used.",
    )

    active = models.BooleanField(default=True, help_text="If false, coupon cannot be applied.")
    starts_at = models.DateTimeField(blank=True, null=True, help_text="Coupon valid from (inclusive).")
    ends_at = models.DateTimeField(blank=True, null=True, help_text="Coupon valid until (exclusive).")

    min_order_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Minimum order subtotal required to apply coupon.",
    )

    max_redemptions = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Global maximum successful redemptions (null = unlimited).",
    )
    max_uses_per_user = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Maximum successful uses per user (null = unlimited).",
    )

    redemption_count = models.PositiveIntegerField(
        default=0,
        help_text="Successful uses count (maintained by system).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["active", "starts_at", "ends_at"]),
        ]
        ordering = ["code"]

    def __str__(self):
        return self.code

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.discount_type == self.DiscountType.PERCENT:
            if self.percent_off is None:
                raise ValidationError({"percent_off": "percent_off is required for percentage coupons."})
            if self.percent_off < 0 or self.percent_off > 100:
                raise ValidationError({"percent_off": "percent_off must be between 0 and 100."})

        if self.discount_type == self.DiscountType.FIXED:
            # either fixed_amount_off or legacy amount must exist
            if self.fixed_amount_off is None and (self.amount is None or float(self.amount) <= 0.0):
                # allow 0? no: a 0 discount is useless; but legacy might have 0 in DB. Keep soft.
                pass

        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "ends_at must be after starts_at."})

    # PUBLIC_INTERFACE
    def is_currently_valid(self, *, now=None) -> bool:
        """Return True if the coupon is active and within its validity window."""
        if not self.active:
            return False
        now = now or timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now >= self.ends_at:
            return False
        return True

    # PUBLIC_INTERFACE
    def compute_discount(self, *, subtotal: Decimal) -> Decimal:
        """Compute discount amount for a given subtotal.

        Notes:
        - discount is capped to subtotal (never negative total).
        - subtotal should be a Decimal (2dp).
        """
        subtotal = _to_decimal_money(subtotal)

        if subtotal <= 0:
            return Decimal("0.00")

        if self.discount_type == self.DiscountType.PERCENT:
            pct = self.percent_off if self.percent_off is not None else Decimal("0.00")
            discount = (subtotal * pct / Decimal("100.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            fixed = self.fixed_amount_off
            if fixed is None:
                fixed = _to_decimal_money(self.amount)
            discount = _to_decimal_money(fixed)

        if discount < 0:
            discount = Decimal("0.00")
        if discount > subtotal:
            discount = subtotal
        return discount


class CouponRedemption(models.Model):
    """Tracks coupon usage for enforcing per-user and global limits.

    We record redemptions only for successful paid orders.
    """

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coupon_redemptions")
    order = models.ForeignKey("Order", on_delete=models.CASCADE, related_name="coupon_redemption")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["coupon", "order"], name="uniq_coupon_redemption_coupon_order"),
        ]
        indexes = [
            models.Index(fields=["coupon", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["coupon", "user", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"redemption:{self.coupon_id}:{self.user_id}:{self.order_id}"


class Order(models.Model):
    """Customer order.

    NOTE: Historically this project used boolean flags for lifecycle tracking.
    This implementation introduces an explicit lifecycle with `status` and milestone
    timestamps while keeping the old boolean fields for backward compatibility.
    """

    class OrderStatus(models.TextChoices):
        PLACED = "placed", "Placed"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ref_code = models.CharField(max_length=20, blank=True, null=True)
    items = models.ManyToManyField(OrderItem)
    start_date = models.DateTimeField(auto_now_add=True)
    ordered_date = models.DateTimeField()
    ordered = models.BooleanField(default=False)
    shipping_address = models.ForeignKey(
        "Address", related_name="shipping_address", on_delete=models.SET_NULL, blank=True, null=True
    )
    billing_address = models.ForeignKey(
        "Address", related_name="billing_address", on_delete=models.SET_NULL, blank=True, null=True
    )
    payment = models.ForeignKey("Payment", on_delete=models.SET_NULL, blank=True, null=True)
    coupon = models.ForeignKey("Coupon", on_delete=models.SET_NULL, blank=True, null=True)

    # Legacy lifecycle fields (kept for backward compatibility with templates/data)
    being_delivered = models.BooleanField(default=False)
    received = models.BooleanField(default=False)

    refund_requested = models.BooleanField(default=False)
    refund_granted = models.BooleanField(default=False)

    # New explicit lifecycle fields
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PLACED,
        db_index=True,
        help_text="Explicit order lifecycle status.",
    )
    placed_at = models.DateTimeField(blank=True, null=True)
    shipped_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)

    """
    1. Item added to cart
    2. Adding a billing address
    (Failed checkout)
    3. Payment
    (Preprocessing, processing, packaging etc.)
    4. Being delivered
    5. Received
    6. Refunds
    """

    def __str__(self):
        return self.user.username

    # PUBLIC_INTERFACE
    def get_subtotal(self) -> float:
        """Return order subtotal (before coupons) as float.

        Keep float for backward compatibility with templates and Stripe integration.
        """
        total = Decimal("0.00")
        for order_item in self.items.all():
            total += _to_decimal_money(order_item.get_final_price())
        return float(total)

    # PUBLIC_INTERFACE
    def get_coupon_discount(self) -> float:
        """Return coupon discount amount applied to this order (0 if none)."""
        subtotal = _to_decimal_money(self.get_subtotal())
        if not self.coupon:
            return 0.0
        discount = self.coupon.compute_discount(subtotal=subtotal)
        return float(discount)

    def get_total(self):
        """Return total for payment.

        Backward compatibility:
          - Existing templates call object.get_total in order_summary.html.
          - Existing Stripe payment flow calls order.get_total().

        New behavior:
          - Supports percent/fixed coupons.
          - Enforces min order total at application time (apply flow), but total calculation
            is also defensive and will not apply coupon discount if subtotal < min_order_total.
        """
        subtotal = _to_decimal_money(self.get_subtotal())
        total = subtotal

        if self.coupon:
            # Defensive: only apply discount if subtotal meets min requirement and coupon is currently valid.
            if subtotal >= _to_decimal_money(self.coupon.min_order_total) and self.coupon.is_currently_valid():
                total -= _to_decimal_money(self.get_coupon_discount())

        if total < 0:
            total = Decimal("0.00")
        return float(total)

    # PUBLIC_INTERFACE
    def status_history(self) -> list[dict]:
        """Return a stable status history for UI/API display.

        Returns:
            List of dicts: [{status: <str>, at: <datetime|None>}]
        """
        return [
            {"status": self.OrderStatus.PLACED, "at": self.placed_at},
            {"status": self.OrderStatus.SHIPPED, "at": self.shipped_at},
            {"status": self.OrderStatus.DELIVERED, "at": self.delivered_at},
        ]

    # PUBLIC_INTERFACE
    def can_transition_to(self, new_status: str) -> bool:
        """Return whether transitioning to `new_status` is allowed.

        Transition rules (simple linear lifecycle):
            placed -> shipped -> delivered

        Same-status transition is allowed as a no-op.

        Important:
            We do not allow transitioning *unpaid carts* beyond PLACED. This prevents
            admins or buggy callers from shipping/delivering an order that was never paid.
        """
        allowed_next = {
            self.OrderStatus.PLACED: {self.OrderStatus.PLACED, self.OrderStatus.SHIPPED},
            self.OrderStatus.SHIPPED: {self.OrderStatus.SHIPPED, self.OrderStatus.DELIVERED},
            self.OrderStatus.DELIVERED: {self.OrderStatus.DELIVERED},
        }

        if not self.ordered and new_status in {self.OrderStatus.SHIPPED, self.OrderStatus.DELIVERED}:
            return False

        return new_status in allowed_next.get(self.status, set())

    # PUBLIC_INTERFACE
    def transition_to(self, new_status: str, *, actor=None, at: timezone.datetime | None = None) -> None:
        """Transition the order to a new status with validation and milestone timestamps.

        Args:
            new_status: One of OrderStatus values.
            actor: Optional user performing the transition (for future auditability).
            at: Timestamp to use; defaults to timezone.now().

        Raises:
            ValueError: if new_status is invalid or transition is not allowed.
        """
        if new_status not in {c.value for c in self.OrderStatus}:
            raise ValueError("Invalid order status.")
        if not self.can_transition_to(new_status):
            raise ValueError(f"Invalid transition from '{self.status}' to '{new_status}'.")

        now = at or timezone.now()

        # Apply transition and set milestone timestamp once.
        self.status = new_status

        # Only a paid order should get placed_at. Carts (ordered=False) may also have
        # status=placed, but they are not "placed orders" until payment succeeds.
        if self.ordered and self.placed_at is None:
            self.placed_at = self.ordered_date or now

        if new_status == self.OrderStatus.SHIPPED:
            if self.shipped_at is None:
                self.shipped_at = now
            # Back-compat mapping
            self.being_delivered = True
            self.received = False

        if new_status == self.OrderStatus.DELIVERED:
            if self.delivered_at is None:
                self.delivered_at = now
            # Back-compat mapping
            self.being_delivered = True
            self.received = True

    # PUBLIC_INTERFACE
    def sync_status_from_legacy_flags(self) -> None:
        """Derive `status` fields from legacy boolean flags.

        This is used for backward-compatible migration and for defensive sync in
        environments where legacy flags may still be modified.
        """
        # Determine desired status
        if self.received:
            desired = self.OrderStatus.DELIVERED
        elif self.being_delivered:
            desired = self.OrderStatus.SHIPPED
        else:
            desired = self.OrderStatus.PLACED

        # Only apply if transition is valid.
        if self.can_transition_to(desired):
            self.transition_to(desired)

    # PUBLIC_INTERFACE
    def sync_legacy_flags_from_status(self) -> None:
        """Set legacy flags based on current explicit `status`."""
        if self.status == self.OrderStatus.PLACED:
            self.being_delivered = False
            self.received = False
        elif self.status == self.OrderStatus.SHIPPED:
            self.being_delivered = True
            self.received = False
        elif self.status == self.OrderStatus.DELIVERED:
            self.being_delivered = True
            self.received = True

    # PUBLIC_INTERFACE
    def validate_coupon_applicable(self, coupon: Coupon, *, user, now=None) -> None:
        """Validate whether a coupon may be applied to this order.

        Raises:
            ValueError with user-safe reason if not applicable.
        """
        now = now or timezone.now()

        if coupon is None:
            raise ValueError("Coupon not found.")

        if not coupon.is_currently_valid(now=now):
            raise ValueError("This coupon is not active or is outside its validity window.")

        subtotal = _to_decimal_money(self.get_subtotal())
        if subtotal < _to_decimal_money(coupon.min_order_total):
            raise ValueError(f"Order total must be at least ${coupon.min_order_total} to use this coupon.")

        # Global max redemptions
        if coupon.max_redemptions is not None and coupon.redemption_count >= int(coupon.max_redemptions):
            raise ValueError("This coupon has reached its maximum number of redemptions.")

        # Per-user usage limits: count successful redemptions
        if coupon.max_uses_per_user is not None:
            used = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
            if used >= int(coupon.max_uses_per_user):
                raise ValueError("You have reached the usage limit for this coupon.")

    # PUBLIC_INTERFACE
    def apply_coupon(self, coupon: Coupon, *, user) -> None:
        """Apply a coupon to this order after validation.

        This does not increment redemption counts; that occurs only upon successful payment.
        """
        self.validate_coupon_applicable(coupon, user=user)
        self.coupon = coupon

    # PUBLIC_INTERFACE
    def remove_coupon(self) -> None:
        """Remove coupon from order (idempotent)."""
        self.coupon = None

    # PUBLIC_INTERFACE
    def record_coupon_redemption_if_needed(self) -> None:
        """Record coupon redemption for paid order and update counters.

        This should be called once, after the order is successfully paid/marked ordered=True.
        It is safe to call multiple times; it is idempotent per-order via unique constraint.
        """
        if not self.ordered or not self.coupon:
            return

        # Ensure we never record redemption for a coupon that wasn't actually valid/applicable.
        coupon = self.coupon
        if not coupon.is_currently_valid():
            return
        subtotal = _to_decimal_money(self.get_subtotal())
        if subtotal < _to_decimal_money(coupon.min_order_total):
            return

        with transaction.atomic():
            # lock coupon for consistent counter checks/updates
            coupon_locked = Coupon.objects.select_for_update().get(pk=coupon.pk)

            # Double-check global limits under lock
            if coupon_locked.max_redemptions is not None and coupon_locked.redemption_count >= int(coupon_locked.max_redemptions):
                return

            # Create redemption (idempotent)
            redemption, created = CouponRedemption.objects.get_or_create(
                coupon=coupon_locked,
                order=self,
                defaults={"user": self.user},
            )
            if created:
                Coupon.objects.filter(pk=coupon_locked.pk).update(
                    redemption_count=F("redemption_count") + 1,
                    updated_at=timezone.now(),
                )


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    street_address = models.CharField(max_length=100)
    apartment_address = models.CharField(max_length=100)
    country = CountryField(multiple=False)
    zip = models.CharField(max_length=100)
    address_type = models.CharField(max_length=1, choices=ADDRESS_CHOICES)
    default = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

    class Meta:
        verbose_name_plural = "Addresses"


class Payment(models.Model):
    # Legacy: kept for backward compatibility with existing charge-based flow.
    stripe_charge_id = models.CharField(max_length=50, blank=True, null=True)

    # New: PaymentIntents-based flow identifiers.
    stripe_payment_intent_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    stripe_payment_intent_client_secret = models.CharField(max_length=255, blank=True, null=True)

    # Webhook idempotency: store the Stripe event id we processed.
    stripe_event_id = models.CharField(max_length=128, blank=True, null=True, unique=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    amount = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # Defensive: user can be null for webhook-created payments in edge cases.
        return self.user.username if self.user else f"payment-{self.pk}"


class Refund(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    reason = models.TextField()
    accepted = models.BooleanField(default=False)
    email = models.EmailField()

    def __str__(self):
        return f"{self.pk}"


class Review(models.Model):
    """Product review created by a user for an item."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Rating from 1 to 5.",
    )
    title = models.CharField(max_length=200, blank=True, null=True)
    body = models.TextField(help_text="Review text.")

    is_hidden = models.BooleanField(
        default=False,
        help_text="If true, this review is hidden from public display (moderation).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "item"], name="uniq_review_user_item"),
        ]
        indexes = [
            models.Index(fields=["item", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["item", "is_hidden", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"review:{self.item_id}:{self.user_id}:{self.rating}"

    def clean(self):
        # rating is PositiveSmallInteger; enforce upper bound here for friendly error surfaces
        from django.core.exceptions import ValidationError

        if self.rating is None:
            raise ValidationError({"rating": "Please select a rating from 1 to 5."})
        if int(self.rating) < 1 or int(self.rating) > 5:
            raise ValidationError({"rating": "Rating must be between 1 and 5."})


# PUBLIC_INTERFACE
def user_has_purchased_item(user, item: Item) -> bool:
    """Return whether user has purchased the given item.

    Detectability policy:
    - We consider a purchase if there exists an Order where ordered=True (paid)
      and one of its OrderItems references the item.

    This helper is used to gate review creation (purchaser-only) where possible.

    Args:
        user: Django auth user
        item: Item instance

    Returns:
        bool: True if user has at least one paid order containing the item.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    # Uses existing schema: Order.items is a M2M to OrderItem which contains item FK.
    return Order.objects.filter(
        user=user,
        ordered=True,
        items__item_id=item.id,
    ).exists()


def userprofile_receiver(sender, instance, created, *args, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


post_save.connect(userprofile_receiver, sender=settings.AUTH_USER_MODEL)
