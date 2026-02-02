from django.urls import path

from .stripe_webhooks import stripe_webhook
from .views import (
    ItemDetailView,
    CheckoutView,
    HomeView,
    OrderSummaryView,
    add_to_cart,
    remove_from_cart,
    remove_single_item_from_cart,
    PaymentView,
    AddCouponView,
    RequestRefundView,
    admin_order_list,
    admin_order_transition,
    my_orders,
)
from .api_views import (
    api_admin_items,
    api_admin_item_detail,
    api_admin_inventory_adjust,
    api_admin_orders,
    api_admin_order_detail,
    api_admin_order_transition,
    api_my_orders,
    api_me,
)
from .api_wishlist import (
    api_wishlist_add,
    api_wishlist_list,
    api_wishlist_remove,
)
from .wishlist_views import wishlist_list, wishlist_toggle

app_name = 'core'

urlpatterns = [
    # Storefront
    path('', HomeView.as_view(), name='home'),
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('order-summary/', OrderSummaryView.as_view(), name='order-summary'),
    path('product/<slug>/', ItemDetailView.as_view(), name='product'),
    path('add-to-cart/<slug>/', add_to_cart, name='add-to-cart'),
    path('add-coupon/', AddCouponView.as_view(), name='add-coupon'),
    path('remove-from-cart/<slug>/', remove_from_cart, name='remove-from-cart'),
    path('remove-item-from-cart/<slug>/', remove_single_item_from_cart,
         name='remove-single-item-from-cart'),
    path('payment/<payment_option>/', PaymentView.as_view(), name='payment'),
    path('request-refund/', RequestRefundView.as_view(), name='request-refund'),

    # Wishlist (template/session auth)
    path('wishlist/', wishlist_list, name='wishlist'),
    path('wishlist/toggle/<slug>/', wishlist_toggle, name='wishlist-toggle'),

    # Stripe webhook (signature verified if STRIPE_WEBHOOK_SECRET is set)
    path('stripe/webhook/', stripe_webhook, name='stripe-webhook'),

    # User order history (template)
    path('my/orders/', my_orders, name='my-orders'),

    # Admin-only management endpoints for template flows (separate from public storefront).
    path('manage/orders/', admin_order_list, name='admin-order-list'),
    path('manage/orders/<int:order_id>/transition/', admin_order_transition, name='admin-order-transition'),

    # API: basic + user
    path('api/me/', api_me, name='api-me'),
    path('api/orders/me/', api_my_orders, name='api-my-orders'),

    # API: wishlist (JWT/session auth via DRF auth classes; requires authenticated)
    path('api/wishlist/', api_wishlist_list, name='api-wishlist-list'),
    path('api/wishlist/add/', api_wishlist_add, name='api-wishlist-add'),
    path('api/wishlist/remove/', api_wishlist_remove, name='api-wishlist-remove'),

    # API: admin (JWT + admin role)
    path('api/admin/items/', api_admin_items, name='api-admin-items'),
    path('api/admin/items/<int:item_id>/', api_admin_item_detail, name='api-admin-item-detail'),
    path('api/admin/inventory/adjust/', api_admin_inventory_adjust, name='api-admin-inventory-adjust'),

    path('api/admin/orders/', api_admin_orders, name='api-admin-orders'),
    path('api/admin/orders/<int:order_id>/', api_admin_order_detail, name='api-admin-order-detail'),
    path('api/admin/orders/<int:order_id>/transition/', api_admin_order_transition, name='api-admin-order-transition'),
]
