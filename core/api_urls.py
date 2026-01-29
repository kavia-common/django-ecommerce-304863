"""
API URL configuration for the core app.

This module is intentionally separate from the template-based URLConf to ensure
we can evolve an API surface (JWT/DRF) without impacting existing UI routes.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.api_viewsets import ProductViewSet, WishlistViewSet
from core.api_views import (
    AdminCouponDetailAPIView,
    AdminCouponListCreateAPIView,
    AdminItemDetailAPIView,
    AdminItemListCreateAPIView,
    AdminOrderStatusTransitionAPIView,
    AdminRefundModerationAPIView,
    DummyPaymentSimulateAPIView,
    HealthAPIView,
    MyOrderDetailAPIView,
    MyOrdersListAPIView,
    PublicItemDetailAPIView,
    PublicItemListAPIView,
)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")
router.register(r"wishlist", WishlistViewSet, basename="wishlist")

urlpatterns = [
    # Utility
    path("health/", HealthAPIView.as_view(), name="api-health"),
    # Product API (public read-only + admin CRUD on same routes)
    path("", include(router.urls)),
    # Legacy public/admin product APIViews (kept for backwards compatibility; do not use for new clients)
    path("products-legacy/", PublicItemListAPIView.as_view(), name="api-products-legacy"),
    path(
        "products-legacy/<int:item_id>/",
        PublicItemDetailAPIView.as_view(),
        name="api-product-detail-legacy",
    ),
    path("admin/products-legacy/", AdminItemListCreateAPIView.as_view(), name="api-admin-products-legacy"),
    path(
        "admin/products-legacy/<int:item_id>/",
        AdminItemDetailAPIView.as_view(),
        name="api-admin-product-detail-legacy",
    ),
    # Customer (JWT/session) endpoints
    path("me/orders/", MyOrdersListAPIView.as_view(), name="api-my-orders"),
    path("me/orders/<int:order_id>/", MyOrderDetailAPIView.as_view(), name="api-my-order-detail"),
    path("me/payments/dummy/simulate/", DummyPaymentSimulateAPIView.as_view(), name="api-dummy-payment-simulate"),
    # Admin (RBAC enforced via DRF permissions)
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
