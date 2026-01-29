"""
Review API viewsets.

This module is split out to keep core/api_viewsets.py from growing too large.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.api_serializers import (ReviewAdminSerializer,
                                  ReviewModerationSerializer,
                                  ReviewPublicSerializer,
                                  ReviewWriteSerializer)
from core.models import Review
from core.permissions import IsAdminGroupOrDjangoPermission


class ReviewViewSet(ModelViewSet):
    """
    Review endpoints with moderation.

    Public:
      - list/retrieve show APPROVED reviews only.

    Authenticated users:
      - can create a review (one per user per item)
      - can update/delete their own review *only while it is unapproved*
      - if a user edits an approved review, it is set back to unapproved (re-moderation)

    Admins:
      - can list/retrieve all reviews (approved + unapproved)
      - can approve/reject via custom actions
      - can delete any review
    """

    queryset = Review.objects.all().select_related("user", "item")

    def _is_adminish(self, user) -> bool:
        return bool(
            user
            and getattr(user, "is_authenticated", False)
            and (
                getattr(user, "is_superuser", False)
                or user.groups.filter(name="Admin").exists()
            )
        )

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]

        if self.action in ("approve", "reject", "moderate", "admin_list"):
            return [IsAuthenticated(), IsAdminGroupOrDjangoPermission()]

        # create/update/partial_update/destroy require authentication;
        # object-level rules are enforced in perform_update/perform_destroy.
        return [IsAuthenticated()]

    # Attribute consumed by IsAdminGroupOrDjangoPermission
    required_django_perms = (
        "core.add_review",
        "core.change_review",
        "core.delete_review",
        "core.view_review",
    )

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)

        # Public list/retrieve only shows approved reviews.
        if self.action in ("list", "retrieve"):
            if not self._is_adminish(user):
                qs = qs.filter(is_approved=True)

        return qs

    def get_serializer_class(self):
        user = getattr(self.request, "user", None)
        if self._is_adminish(user):
            # For admins, default to admin serializer unless public list/retrieve explicitly asked.
            if self.action in ("list", "retrieve"):
                # Admins still should see full moderation fields if authenticated.
                if getattr(user, "is_authenticated", False):
                    return ReviewAdminSerializer
                return ReviewPublicSerializer
            return ReviewAdminSerializer

        if self.action in ("list", "retrieve"):
            return ReviewPublicSerializer

        return ReviewWriteSerializer

    def perform_create(self, serializer):
        """
        Users create their own review.

        This enforces:
          - one review per user+item (unique constraint)
          - new reviews default to unapproved
        """
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            # Likely duplicate unique constraint.
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"detail": "You have already reviewed this product."})

    def _ensure_owner_or_admin(self, obj):
        user = getattr(self.request, "user", None)
        if self._is_adminish(user):
            return
        if obj.user_id != getattr(user, "id", None):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only modify your own reviews.")

    def perform_update(self, serializer):
        """
        Update behavior:

        - Non-admin users can only edit their own review.
        - If review is already approved and user edits it, it becomes unapproved again.
        - Alternatively, you can restrict editing approved reviews entirely; here we
          allow it but require re-approval (as requested).
        """
        obj = self.get_object()
        self._ensure_owner_or_admin(obj)

        user = getattr(self.request, "user", None)
        is_adminish = self._is_adminish(user)

        updated = serializer.save()

        if not is_adminish and updated.is_approved:
            # User edited an approved review: force re-moderation.
            Review.objects.filter(pk=updated.pk).update(is_approved=False)
            updated.is_approved = False

    def perform_destroy(self, instance):
        obj = instance
        self._ensure_owner_or_admin(obj)

        user = getattr(self.request, "user", None)
        if not self._is_adminish(user):
            # Non-admins can delete only if unapproved (avoid removing moderated public content).
            if obj.is_approved:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied(
                    "Approved reviews cannot be deleted by users. Contact support."
                )
        obj.delete()

    # PUBLIC_INTERFACE
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsAuthenticated, IsAdminGroupOrDjangoPermission],
        url_path="admin",
    )
    def admin_list(self, request):
        """
        Admin-only list endpoint for all reviews.

        Route:
          GET /api/reviews/admin/
        """
        qs = (
            Review.objects.all()
            .select_related("user", "item")
            .order_by("-created_at", "-id")
        )

        page = getattr(self, "paginator", None)
        if page is None:
            from rest_framework.pagination import PageNumberPagination

            self.paginator = PageNumberPagination()
            page = self.paginator

        paged = page.paginate_queryset(qs, request, view=self)
        serializer = ReviewAdminSerializer(
            paged if paged is not None else qs, many=True
        )
        if paged is not None:
            return page.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # PUBLIC_INTERFACE
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsAdminGroupOrDjangoPermission],
        url_path="approve",
    )
    def approve(self, request, pk=None):
        """
        Approve a review.

        Route:
          POST /api/reviews/{id}/approve/
        """
        review = self.get_object()
        review.is_approved = True
        review.save(update_fields=["is_approved", "updated_at"])
        return Response(ReviewAdminSerializer(review).data, status=status.HTTP_200_OK)

    # PUBLIC_INTERFACE
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsAdminGroupOrDjangoPermission],
        url_path="reject",
    )
    def reject(self, request, pk=None):
        """
        Reject/unapprove a review.

        Route:
          POST /api/reviews/{id}/reject/
        """
        review = self.get_object()
        review.is_approved = False
        review.save(update_fields=["is_approved", "updated_at"])
        return Response(ReviewAdminSerializer(review).data, status=status.HTTP_200_OK)

    # PUBLIC_INTERFACE
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsAdminGroupOrDjangoPermission],
        url_path="moderate",
    )
    def moderate(self, request, pk=None):
        """
        Generic moderation endpoint to set is_approved.

        Route:
          POST /api/reviews/{id}/moderate/  body: { "is_approved": true|false }
        """
        review = self.get_object()
        ser = ReviewModerationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        review.is_approved = ser.validated_data["is_approved"]
        review.save(update_fields=["is_approved", "updated_at"])
        return Response(ReviewAdminSerializer(review).data, status=status.HTTP_200_OK)
