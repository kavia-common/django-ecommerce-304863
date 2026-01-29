"""
API URL configuration for the core app.

This module is intentionally separate from the template-based URLConf to ensure
we can evolve an API surface (JWT/DRF) without impacting existing UI routes.
"""

from django.urls import path

from core.api_views import (
    AdminCouponDetailAPIView,
    AdminCouponListCreateAPIView,
    AdminItemDetailAPIView,
    AdminItemListCreateAPIView,
    AdminOrderStatusTransitionAPIView,
    AdminRefundModerationAPIView,
    AdminRefundModerationAPIView,
    HealthAPIView,
    MyOrderDetailAPIView,
    MyOrdersListAPIView,
    PublicItemDetailAPIView,
    PublicItemListAPIView,
)

urlpatterns = [
    # Utility
    path("health/", HealthAPIView.as_view(), name="api-health"),
    # Public read-only catalog
    path("products/", PublicItemListAPIView.as_view(), name="api-products"),
    path("products/<int:item_id>/", PublicItemDetailAPIView.as_view(), name="api-product-detail"),
    # Customer (JWT/session) endpoints
    path("me/orders/", MyOrdersListAPIView.as_view(), name="api-my-orders"),
    path("me/orders/<int:order_id>/", MyOrderDetailAPIView.as_view(), name="api-my-order-detail"),
    # Admin (RBAC enforced via DRF permissions)
    path("admin/products/", AdminItemListCreateAPIView.as_view(), name="api-admin-products"),
    path("admin/products/<int:item_id>/", AdminItemDetailAPIView.as_view(), name="api-admin-product-detail"),
    path("admin/coupons/", AdminCouponListCreateAPIView.as_view(), name="api-admin-coupons"),
    path("admin/coupons/<int:coupon_id>/", AdminCouponDetailAPIView.as_view(), name="api-admin-coupon-detail"),
    path(
        "admin/orders/<int:order_id>/transition/",
        AdminOrderStatusTransitionAPIView.as_view(),
        name="api-admin-order-transition",
    ),
    path(
        "admin/refunds/<int:refund_id>/moderate/",
        AdminRefundModerationAPIView.as_view(),
        name="api-admin-refund-moderate",
    ),
]
