from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.shortcuts import reverse
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ref_code = models.CharField(max_length=20, blank=True, null=True)
    items = models.ManyToManyField(OrderItem)
    start_date = models.DateTimeField(auto_now_add=True)
    ordered_date = models.DateTimeField()
    ordered = models.BooleanField(default=False)
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
    being_delivered = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    refund_requested = models.BooleanField(default=False)
    refund_granted = models.BooleanField(default=False)

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

    def get_total(self):
        total = 0
        for order_item in self.items.all():
            total += order_item.get_final_price()
        if self.coupon:
            total -= self.coupon.amount
        return total


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
