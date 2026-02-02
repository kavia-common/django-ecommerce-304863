from django.contrib import admin

from .models import Item, OrderItem, Order, Payment, Coupon, Refund, Address, UserProfile, Category


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
    list_display = ["title", "sku", "active", "price", "discount_price", "category", "category_obj", "updated_at"]
    list_filter = ["active", "category", "category_obj"]
    search_fields = ["title", "sku", "slug", "description"]
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ["created_at", "updated_at"]


admin.site.register(OrderItem)
admin.site.register(Order, OrderAdmin)
admin.site.register(Payment)
admin.site.register(Coupon)
admin.site.register(Refund)
admin.site.register(Address, AddressAdmin)
admin.site.register(UserProfile)
