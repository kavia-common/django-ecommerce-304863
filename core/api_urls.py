"""
API URL configuration for the core app.

This module is intentionally separate from the template-based URLConf to ensure
we can evolve an API surface (JWT/DRF) without impacting existing UI routes.

Order routes (new canonical):
- User:
  - GET /api/orders/active/
  - GET /api/orders/
  - GET /api/orders/{id}/
- Admin:
  - GET /api/admin/orders/
  - GET /api/admin/orders/{id}/
  - POST /api/admin/orders/{id}/transition/
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.api_viewsets import ProductViewSet, WishlistViewSet
from core.api_views import (
    AdminCouponDetailAPIView,
    AdminCouponListCreateAPIView,
    AdminOrderDetailAPIView,
    AdminOrderListAPIView,
    AdminOrderStatusTransitionAPIView,
    AdminRefundModerationAPIView,
    DummyPaymentSimulateAPIView,
    HealthAPIView,
    MyActiveOrderCheckoutSummaryAPIView,
    MyOrderDetailAPIView,
    MyOrdersListAPIView,
    PublicItemDetailAPIView,
    PublicItemListAPIView,
)
from core.reviews_viewset import ReviewViewSet

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")
router.register(r"wishlist", WishlistViewSet, basename="wishlist")
router.register(r"reviews", ReviewViewSet, basename="reviews")

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
    # User order endpoints (JWT/session)
    path("orders/active/", MyActiveOrderCheckoutSummaryAPIView.as_view(), name="api-orders-active"),
    path("orders/", MyOrdersListAPIView.as_view(), name="api-orders"),
    path("orders/<int:order_id>/", MyOrderDetailAPIView.as_view(), name="api-order-detail"),
    path("me/payments/dummy/simulate/", DummyPaymentSimulateAPIView.as_view(), name="api-dummy-payment-simulate"),
    # Admin endpoints (RBAC enforced via DRF permissions)
    path("admin/coupons/", AdminCouponListCreateAPIView.as_view(), name="api-admin-coupons"),
    path("admin/coupons/<int:coupon_id>/", AdminCouponDetailAPIView.as_view(), name="api-admin-coupon-detail"),
    path("admin/orders/", AdminOrderListAPIView.as_view(), name="api-admin-orders"),
    path("admin/orders/<int:order_id>/", AdminOrderDetailAPIView.as_view(), name="api-admin-order-detail"),
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
