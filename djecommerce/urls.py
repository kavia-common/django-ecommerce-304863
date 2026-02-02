from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from core.views import api_me
from core.api_views import (
    api_admin_items,
    api_admin_item_detail,
    api_admin_inventory_adjust,
    api_admin_order_transition,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # Existing session-based auth for templates (unchanged)
    path('accounts/', include('allauth.urls')),

    # JWT auth for API clients (new)
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # Minimal JWT-protected example endpoint (verifies DRF+SimpleJWT wiring)
    path('api/auth/me/', api_me, name='api_me'),

    # Admin-only API surface (RBAC enforced by DRF permission classes)
    path('api/admin/items/', api_admin_items, name='api_admin_items'),
    path('api/admin/items/<int:item_id>/', api_admin_item_detail, name='api_admin_item_detail'),
    path('api/admin/inventory/adjust/', api_admin_inventory_adjust, name='api_admin_inventory_adjust'),
    path('api/admin/orders/<int:order_id>/transition/', api_admin_order_transition, name='api_admin_order_transition'),

    path('', include('core.urls', namespace='core'))
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)
