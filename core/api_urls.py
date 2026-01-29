"""
API URL configuration for the core app.

This module is intentionally separate from the template-based URLConf to ensure
we can evolve an API surface (JWT/DRF) without impacting existing UI routes.
"""

from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthAPIView(APIView):
    """Simple health check endpoint to verify DRF wiring."""

    permission_classes = [AllowAny]

    # PUBLIC_INTERFACE
    def get(self, request, *args, **kwargs):
        """Return a small payload indicating the API is reachable."""
        return Response({"status": "ok"})


urlpatterns = [
    path("health/", HealthAPIView.as_view(), name="api-health"),
]
