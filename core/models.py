from django.db.models.signals import post_save
from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Sum
from django.shortcuts import reverse
from django.utils import timezone
from django.core.validators import MinValueValidator
from django_countries.fields import CountryField


CATEGORY_CHOICES = (
    ('S', 'Shirt'),
    ('SW', 'Sport wear'),
    ('OW', 'Outwear')
)

LABEL_CHOICES = (
    ('P', 'primary'),
    ('S', 'secondary'),
    ('D', 'danger')
)

ADDRESS_CHOICES = (
    ('B', 'Billing'),
    ('S', 'Shipping'),
)


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
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
        return reverse("core:product", kwargs={
            'slug': self.slug
        })

    def get_add_to_cart_url(self):
        return reverse("core:add-to-cart", kwargs={
            'slug': self.slug
        })

    def get_remove_from_cart_url(self):
        return reverse("core:remove-from-cart", kwargs={
            'slug': self.slug
        })

    def get_storefront_image(self):
        """Return best-available image for storefront display (template-safe)."""
        if self.primary_image:
            return self.primary_image
        return self.image


class OrderItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
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

    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    ref_code = models.CharField(max_length=20, blank=True, null=True)
    items = models.ManyToManyField(OrderItem)
    start_date = models.DateTimeField(auto_now_add=True)
    ordered_date = models.DateTimeField()
    ordered = models.BooleanField(default=False)
    shipping_address = models.ForeignKey(
        'Address', related_name='shipping_address', on_delete=models.SET_NULL, blank=True, null=True)
    billing_address = models.ForeignKey(
        'Address', related_name='billing_address', on_delete=models.SET_NULL, blank=True, null=True)
    payment = models.ForeignKey(
        'Payment', on_delete=models.SET_NULL, blank=True, null=True)
    coupon = models.ForeignKey(
        'Coupon', on_delete=models.SET_NULL, blank=True, null=True)

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

    '''
    1. Item added to cart
    2. Adding a billing address
    (Failed checkout)
    3. Payment
    (Preprocessing, processing, packaging etc.)
    4. Being delivered
    5. Received
    6. Refunds
    '''

    def __str__(self):
        return self.user.username

    def get_total(self):
        total = 0
        for order_item in self.items.all():
            total += order_item.get_final_price()
        if self.coupon:
            total -= self.coupon.amount
        return total

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

    def save(self, *args, **kwargs):
        """Ensure status and timestamps remain consistent with legacy flags."""
        # If this is a paid order and placed_at wasn't set yet, set it.
        # (We intentionally do NOT set placed_at for carts.)
        if self.ordered and self.placed_at is None:
            self.placed_at = self.ordered_date or timezone.now()

        # Keep legacy flags consistent with explicit status.
        if self.status:
            self.sync_legacy_flags_from_status()
        else:  # pragma: no cover (status has default; defensive)
            self.sync_status_from_legacy_flags()

        super().save(*args, **kwargs)


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE)
    street_address = models.CharField(max_length=100)
    apartment_address = models.CharField(max_length=100)
    country = CountryField(multiple=False)
    zip = models.CharField(max_length=100)
    address_type = models.CharField(max_length=1, choices=ADDRESS_CHOICES)
    default = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username

    class Meta:
        verbose_name_plural = 'Addresses'


class Payment(models.Model):
    stripe_charge_id = models.CharField(max_length=50)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.SET_NULL, blank=True, null=True)
    amount = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class Coupon(models.Model):
    code = models.CharField(max_length=15)
    amount = models.FloatField()

    def __str__(self):
        return self.code


class Refund(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    reason = models.TextField()
    accepted = models.BooleanField(default=False)
    email = models.EmailField()

    def __str__(self):
        return f"{self.pk}"


def userprofile_receiver(sender, instance, created, *args, **kwargs):
    if created:
        userprofile = UserProfile.objects.create(user=instance)


post_save.connect(userprofile_receiver, sender=settings.AUTH_USER_MODEL)
