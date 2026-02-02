from django.db.models.signals import post_save
from django.conf import settings
from django.db import models
from django.db.models import Sum
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
    being_delivered = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    refund_requested = models.BooleanField(default=False)
    refund_granted = models.BooleanField(default=False)

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
