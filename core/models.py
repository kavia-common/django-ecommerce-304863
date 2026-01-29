from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
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


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stripe_customer_id = models.CharField(max_length=50, blank=True, null=True)
    one_click_purchasing = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


class Item(models.Model):
    """
    Catalog item/product.

    NOTE: Existing storefront behavior relies on `category` being present with CATEGORY_CHOICES,
    so we keep it as a CharField and add inventory-related fields without altering existing flows.
    """

    # Existing catalog fields
    title = models.CharField(max_length=100)
    price = models.FloatField()
    discount_price = models.FloatField(blank=True, null=True)
    category = models.CharField(choices=CATEGORY_CHOICES, max_length=2)
    label = models.CharField(choices=LABEL_CHOICES, max_length=1)
    slug = models.SlugField()
    description = models.TextField()
    image = models.ImageField()

    # New catalog enhancements
    sku = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        help_text="Unique stock keeping unit. Nullable/blank for legacy items.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft-enable/disable product without deleting it.",
    )
    low_stock_threshold = models.IntegerField(
        default=0,
        help_text="Threshold at/below which the product should be considered low stock.",
    )

    # New inventory tracking fields
    stock_on_hand = models.IntegerField(
        default=0,
        help_text="Physical stock currently on hand (available to allocate).",
    )
    stock_reserved = models.IntegerField(
        default=0,
        help_text="Stock reserved for carts/orders not yet fulfilled.",
    )

    def __str__(self):
        return self.title

    # PUBLIC_INTERFACE
    @property
    def available_stock(self) -> int:
        """
        Compute available stock for sale as (on hand - reserved).

        This is intentionally a computed helper (not a DB field) so existing code paths
        remain unchanged while new inventory-aware logic can start using it.
        """
        return int(self.stock_on_hand or 0) - int(self.stock_reserved or 0)

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


class InventoryAdjustment(models.Model):
    """
    Audit log of inventory deltas for an item.

    This model does not automatically mutate stock fields yet; it is introduced as the
    domain primitive for future inventory workflows (receiving stock, returns, cancellations, etc.).
    """

    class Reason(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        SALE = "SALE", "Sale"
        RETURN = "RETURN", "Return"
        DAMAGE = "DAMAGE", "Damage"
        CORRECTION = "CORRECTION", "Correction"
        OTHER = "OTHER", "Other"

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="inventory_adjustments")
    delta = models.IntegerField(help_text="Signed quantity change (e.g. +10 received, -1 sale).")
    reason = models.CharField(max_length=24, choices=Reason.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="inventory_adjustments_created",
    )
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"InventoryAdjustment(item={self.item_id}, delta={self.delta}, reason={self.reason})"


class OrderItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ordered = models.BooleanField(default=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)

    # Inventory workflow tracking (idempotency + audit)
    quantity_reserved = models.IntegerField(
        default=0,
        help_text="Units reserved on the Item for this OrderItem (not yet paid/fulfilled).",
    )
    quantity_committed = models.IntegerField(
        default=0,
        help_text="Units committed (sold) for this OrderItem after payment success.",
    )
    quantity_restocked = models.IntegerField(
        default=0,
        help_text="Units restocked back to on-hand due to refunds/returns.",
    )

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
    """
    Order domain model.

    Legacy site flow uses boolean flags:
      - ordered, being_delivered, received, refund_requested, refund_granted

    New API / domain model uses a single explicit status field + immutable history.
    For backwards compatibility (templates + existing checkout flow), legacy booleans
    remain for now, but are mapped from/to status through helper properties/methods.
    """

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        PAID = "PAID", "Paid"
        FULFILLING = "FULFILLING", "Fulfilling"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ref_code = models.CharField(max_length=20, blank=True, null=True)
    items = models.ManyToManyField(OrderItem)
    start_date = models.DateTimeField(auto_now_add=True)
    ordered_date = models.DateTimeField()
    ordered = models.BooleanField(default=False)

    # New explicit lifecycle status (kept in sync with booleans by transition methods).
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
        help_text="Explicit order lifecycle status.",
    )

    shipping_address = models.ForeignKey(
        "Address",
        related_name="shipping_address",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    billing_address = models.ForeignKey(
        "Address",
        related_name="billing_address",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    payment = models.ForeignKey("Payment", on_delete=models.SET_NULL, blank=True, null=True)
    coupon = models.ForeignKey("Coupon", on_delete=models.SET_NULL, blank=True, null=True)

    # Legacy flags (deprecated; retained temporarily for templates/admin)
    being_delivered = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    refund_requested = models.BooleanField(default=False)
    refund_granted = models.BooleanField(default=False)

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
    def compute_status_from_legacy_flags(self) -> str:
        """
        Compute the status that best represents the legacy boolean flag state.

        This is primarily used during migration/backfill and defensive reads when old code
        has manipulated booleans directly.

        Precedence:
          refunded > cancelled (not represented in legacy) > delivered > shipped-ish > paid > created

        NOTE: legacy does not distinguish FULFILLING vs SHIPPED; being_delivered maps to SHIPPED.
        """
        if self.refund_granted:
            return Order.Status.REFUNDED
        if self.received:
            return Order.Status.DELIVERED
        if self.being_delivered:
            return Order.Status.SHIPPED
        if self.ordered:
            return Order.Status.PAID
        return Order.Status.CREATED

    # PUBLIC_INTERFACE
    def sync_legacy_flags_from_status(self) -> None:
        """
        Update legacy boolean flags to be consistent with the current explicit status.

        This should be called whenever status changes through the new transition API.
        """
        status = self.status
        self.ordered = status in {
            Order.Status.PAID,
            Order.Status.FULFILLING,
            Order.Status.SHIPPED,
            Order.Status.DELIVERED,
            Order.Status.REFUNDED,
        }
        self.being_delivered = status in {Order.Status.SHIPPED, Order.Status.DELIVERED}
        self.received = status == Order.Status.DELIVERED
        # refund_requested is a separate workflow; keep it as-is unless we transition to REFUNDED.
        if status == Order.Status.REFUNDED:
            self.refund_requested = False
            self.refund_granted = True
        elif status in {Order.Status.CREATED, Order.Status.CANCELLED}:
            # If an order is cancelled before payment, refund_granted should not remain true.
            self.refund_granted = False

    def _validate_transition(self, target_status: str) -> None:
        allowed = {
            Order.Status.CREATED: {Order.Status.PAID, Order.Status.CANCELLED},
            Order.Status.PAID: {Order.Status.FULFILLING, Order.Status.CANCELLED, Order.Status.REFUNDED},
            Order.Status.FULFILLING: {Order.Status.SHIPPED, Order.Status.CANCELLED, Order.Status.REFUNDED},
            Order.Status.SHIPPED: {Order.Status.DELIVERED, Order.Status.REFUNDED},
            Order.Status.DELIVERED: {Order.Status.REFUNDED},
            Order.Status.CANCELLED: set(),
            Order.Status.REFUNDED: set(),
        }
        current = self.status
        if target_status == current:
            return
        if target_status not in allowed.get(current, set()):
            raise ValueError(f"Invalid transition {current} -> {target_status}")

    # PUBLIC_INTERFACE
    def transition_status(
        self,
        *,
        target_status: str,
        performed_by=None,
        reason: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict | None = None,
    ) -> "OrderStatusHistory":
        """
        Transition the order to `target_status` with validation + idempotency and record history.

        Idempotency:
          - If an idempotency_key is provided and a history record already exists for this order+key,
            that existing record is returned and no state change occurs.
          - If target_status == current_status, the transition is treated as idempotent and a
            history record is still written (unless idempotency_key already exists).

        performed_by:
          - Optional user reference for audit (admin/system).

        Raises:
          ValueError if transition is invalid.
        """
        if target_status not in Order.Status.values:
            raise ValueError(f"Unknown target status: {target_status}")

        with transaction.atomic():
            # Lock row to ensure consistent transitions under concurrency.
            order = Order.objects.select_for_update().get(pk=self.pk)

            if idempotency_key:
                existing = OrderStatusHistory.objects.filter(
                    order=order, idempotency_key=idempotency_key
                ).first()
                if existing:
                    return existing

            # Validate based on current status.
            order._validate_transition(target_status)

            from_status = order.status
            to_status = target_status

            # Apply status change if needed
            if to_status != from_status:
                order.status = to_status

            # Sync legacy booleans so templates/admin stay consistent.
            order.sync_legacy_flags_from_status()
            order.save()

            history = OrderStatusHistory.objects.create(
                order=order,
                from_status=from_status,
                to_status=to_status,
                performed_by=performed_by,
                idempotency_key=idempotency_key,
                reason=reason or "",
                metadata=metadata or {},
            )
            return history


class OrderStatusHistory(models.Model):
    """
    Immutable audit log of order status transitions.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=16, choices=Order.Status.choices)
    to_status = models.CharField(max_length=16, choices=Order.Status.choices)
    performed_at = models.DateTimeField(auto_now_add=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="order_status_transitions",
    )
    idempotency_key = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="Optional idempotency key to make transitions safe for retries.",
    )
    reason = models.TextField(blank=True, default="")
    metadata = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-performed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "idempotency_key"],
                name="uniq_order_transition_idempotency_key",
                condition=~models.Q(idempotency_key=None),
            )
        ]

    def __str__(self) -> str:
        return f"OrderStatusHistory(order={self.order_id}, {self.from_status}->{self.to_status})"


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
    stripe_charge_id = models.CharField(max_length=50)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True)
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
        UserProfile.objects.create(user=instance)


post_save.connect(userprofile_receiver, sender=settings.AUTH_USER_MODEL)
