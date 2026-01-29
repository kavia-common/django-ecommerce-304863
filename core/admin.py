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
    UserProfile,
)


def make_refund_accepted(modeladmin, request, queryset):
    queryset.update(refund_requested=False, refund_granted=True)


make_refund_accepted.short_description = "Update orders to refund granted"


class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "user",
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
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment)
admin.site.register(Coupon)
admin.site.register(Refund)
admin.site.register(Address, AddressAdmin)
admin.site.register(UserProfile)
