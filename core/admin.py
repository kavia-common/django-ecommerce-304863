from django.contrib import admin

from .models import Item, OrderItem, Order, Payment, Coupon, Refund, Address, UserProfile, Category, WishlistEntry, Review


def make_refund_accepted(modeladmin, request, queryset):
    queryset.update(refund_requested=False, refund_granted=True)


make_refund_accepted.short_description = 'Update orders to refund granted'


class OrderAdmin(admin.ModelAdmin):
    list_display = ['user',
                    'ordered',
                    'being_delivered',
                    'received',
                    'refund_requested',
                    'refund_granted',
                    'shipping_address',
                    'billing_address',
                    'payment',
                    'coupon'
                    ]
    list_display_links = [
        'user',
        'shipping_address',
        'billing_address',
        'payment',
        'coupon'
    ]
    list_filter = ['ordered',
                   'being_delivered',
                   'received',
                   'refund_requested',
                   'refund_granted']
    search_fields = [
        'user__username',
        'ref_code'
    ]
    actions = [make_refund_accepted]


class AddressAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'street_address',
        'apartment_address',
        'country',
        'zip',
        'address_type',
        'default'
    ]
    list_filter = ['default', 'address_type', 'country']
    search_fields = ['user', 'street_address', 'apartment_address', 'zip']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "active", "updated_at"]
    list_filter = ["active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "sku",
        "active",
        "track_inventory",
        "stock_quantity",
        "price",
        "discount_price",
        "category",
        "category_obj",
        "updated_at",
    ]
    list_filter = ["active", "track_inventory", "category", "category_obj"]
    search_fields = ["title", "sku", "slug", "description"]
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ["created_at", "updated_at"]


@admin.action(description="Hide selected reviews")
def hide_reviews(modeladmin, request, queryset):
    queryset.update(is_hidden=True)


@admin.action(description="Unhide selected reviews")
def unhide_reviews(modeladmin, request, queryset):
    queryset.update(is_hidden=False)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "item", "user", "rating", "is_hidden", "created_at", "updated_at"]
    list_filter = ["is_hidden", "rating", "created_at"]
    search_fields = ["item__title", "item__sku", "user__username", "user__email", "title", "body"]
    autocomplete_fields = ["item", "user"]
    readonly_fields = ["created_at", "updated_at"]
    actions = [hide_reviews, unhide_reviews]


admin.site.register(OrderItem)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment)
@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "active",
        "discount_type",
        "amount",
        "fixed_amount_off",
        "percent_off",
        "min_order_total",
        "max_redemptions",
        "redemption_count",
        "max_uses_per_user",
        "starts_at",
        "ends_at",
        "updated_at",
    ]
    list_filter = ["active", "discount_type"]
    search_fields = ["code"]
    readonly_fields = ["redemption_count", "created_at", "updated_at"]


# Keep old registration removed in favor of explicit ModelAdmin above.
admin.site.register(Refund)
admin.site.register(Address, AddressAdmin)
admin.site.register(UserProfile)
admin.site.register(WishlistEntry)
