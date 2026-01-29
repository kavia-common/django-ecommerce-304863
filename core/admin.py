from django.contrib import admin

from .models import (
    Address,
    Coupon,
    InventoryAdjustment,
    Item,
    Order,
    OrderItem,
    Payment,
    Refund,
    Review,
    UserProfile,
    WishlistItem,
)


def make_refund_accepted(modeladmin, request, queryset):
    queryset.update(refund_requested=False, refund_granted=True)


make_refund_accepted.short_description = "Update orders to refund granted"


class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "status",
        "ordered",
        "being_delivered",
        "received",
        "refund_requested",
        "refund_granted",
        "shipping_address",
        "billing_address",
        "payment",
        "coupon",
    ]
    list_display_links = [
        "user",
        "shipping_address",
        "billing_address",
        "payment",
        "coupon",
    ]
    list_filter = [
        "status",
        "ordered",
        "being_delivered",
        "received",
        "refund_requested",
        "refund_granted",
    ]
    search_fields = [
        "user__username",
        "ref_code",
    ]
    actions = [make_refund_accepted]


class AddressAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "street_address",
        "apartment_address",
        "country",
        "zip",
        "address_type",
        "default",
    ]
    list_filter = ["default", "address_type", "country"]
    search_fields = ["user", "street_address", "apartment_address", "zip"]


class ItemAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "sku",
        "category",
        "price",
        "discount_price",
        "is_active",
        "stock_on_hand",
        "stock_reserved",
    ]
    list_filter = ["is_active", "category", "label"]
    search_fields = ["title", "sku", "slug"]


class InventoryAdjustmentAdmin(admin.ModelAdmin):
    list_display = ["item", "delta", "reason", "created_at", "created_by"]
    list_filter = ["reason", "created_at"]
    search_fields = ["item__title", "item__sku", "note", "created_by__username"]


admin.site.register(Item, ItemAdmin)
admin.site.register(InventoryAdjustment, InventoryAdjustmentAdmin)
admin.site.register(OrderItem)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "amount",
        "provider",
        "mode",
        "status",
        "provider_reference",
        "idempotency_key",
        "timestamp",
    ]
    list_filter = ["provider", "mode", "status", "timestamp"]
    search_fields = ["user__username", "provider_reference", "idempotency_key", "stripe_charge_id"]


admin.site.register(Order, OrderAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(Coupon)
admin.site.register(Refund)
admin.site.register(Address, AddressAdmin)
admin.site.register(UserProfile)


class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ["user", "item", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["user__username", "user__email", "item__title", "item__sku", "item__slug"]
    ordering = ["-created_at", "-id"]
    readonly_fields = ["user", "item", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(WishlistItem, WishlistItemAdmin)


def approve_reviews(modeladmin, request, queryset):
    queryset.update(is_approved=True)


approve_reviews.short_description = "Approve selected reviews"


def reject_reviews(modeladmin, request, queryset):
    queryset.update(is_approved=False)


reject_reviews.short_description = "Reject selected reviews"


class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "item", "user", "rating", "is_approved", "created_at", "updated_at"]
    list_filter = ["is_approved", "rating", "created_at"]
    search_fields = ["user__username", "user__email", "item__title", "item__sku", "title", "body"]
    ordering = ["-created_at", "-id"]
    actions = [approve_reviews, reject_reviews]
    readonly_fields = ["created_at", "updated_at"]


admin.site.register(Review, ReviewAdmin)
