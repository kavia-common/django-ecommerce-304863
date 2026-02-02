"""Review & rating API endpoints.

Routes (mounted under /api/reviews/**):
- GET  /api/reviews/items/<item_id>/          Public list (visible reviews only)
- POST /api/reviews/items/<item_id>/          Create or update the authenticated user's review (one per user+item)
- DELETE /api/reviews/items/<item_id>/        Delete the authenticated user's review

Admin moderation:
- POST /api/reviews/<review_id>/hide/         Admin-only hide
- POST /api/reviews/<review_id>/unhide/       Admin-only unhide
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .api_permissions import IsAdminRole
from .models import Item, Review, user_has_purchased_item


class ReviewSerializer(serializers.ModelSerializer):
    """Serializer for public and user-facing review data."""

    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "item",
            "user",
            "user_username",
            "rating",
            "title",
            "body",
            "is_hidden",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "item", "user", "is_hidden", "created_at", "updated_at"]


class ReviewUpsertRequest(serializers.Serializer):
    """Request payload for creating/updating a review."""

    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=200)
    body = serializers.CharField()

    def validate_body(self, value: str) -> str:
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("Please enter your review text.")
        if len(v) < 10:
            raise serializers.ValidationError("Review text is too short (min 10 characters).")
        return v


def _item_review_stats(item: Item) -> dict:
    """Compute public review stats for an item."""
    qs = item.reviews.filter(is_hidden=False)
    agg = qs.aggregate(avg=Avg("rating"), cnt=Count("id"))
    avg = float(agg["avg"]) if agg["avg"] is not None else 0.0
    cnt = int(agg["cnt"] or 0)
    return {"average_rating": avg, "reviews_count": cnt}


# PUBLIC_INTERFACE
@api_view(["GET"])
@permission_classes([AllowAny])
def api_reviews_for_item(request, item_id: int):
    """Public: list visible reviews for an item with simple stats."""
    item = get_object_or_404(Item.all_objects, pk=item_id)

    reviews = (
        item.reviews.filter(is_hidden=False)
        .select_related("user")
        .order_by("-created_at", "-id")
    )
    data = ReviewSerializer(reviews, many=True).data
    return Response(
        {
            "item_id": item.id,
            **_item_review_stats(item),
            "results": data,
        },
        status=status.HTTP_200_OK,
    )


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_upsert_my_review(request, item_id: int):
    """Auth: create or update the authenticated user's review for an item.

    Policy:
    - Requires authentication.
    - Purchaser-only if detectably purchased via orders (ordered=True).
    """
    item = get_object_or_404(Item.all_objects, pk=item_id)

    # purchaser-only gate
    if not user_has_purchased_item(request.user, item):
        return Response(
            {"detail": "Only customers who purchased this item can leave a review."},
            status=status.HTTP_403_FORBIDDEN,
        )

    payload = ReviewUpsertRequest(data=request.data)
    payload.is_valid(raise_exception=True)

    with transaction.atomic():
        review = Review.objects.filter(user=request.user, item=item).first()
        created = False
        if review is None:
            review = Review(user=request.user, item=item)
            created = True

        review.rating = payload.validated_data["rating"]
        review.title = payload.validated_data.get("title") or ""
        review.body = payload.validated_data["body"]

        try:
            review.full_clean()
            review.save()
        except IntegrityError:
            # Unique constraint race: refetch and retry update
            review = Review.objects.get(user=request.user, item=item)
            review.rating = payload.validated_data["rating"]
            review.title = payload.validated_data.get("title") or ""
            review.body = payload.validated_data["body"]
            review.full_clean()
            review.save()
            created = False
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "created": created,
            "review": ReviewSerializer(review).data,
            **_item_review_stats(item),
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


# PUBLIC_INTERFACE
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def api_delete_my_review(request, item_id: int):
    """Auth: delete the authenticated user's review for an item."""
    item = get_object_or_404(Item.all_objects, pk=item_id)
    review = Review.objects.filter(user=request.user, item=item).first()
    if not review:
        return Response({"detail": "You do not have a review for this item."}, status=status.HTTP_404_NOT_FOUND)

    review.delete()
    return Response(
        {"detail": "Your review was deleted.", **_item_review_stats(item)},
        status=status.HTTP_200_OK,
    )


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_hide_review(request, review_id: int):
    """Admin-only: hide a review from public display."""
    review = get_object_or_404(Review.objects.select_related("item"), pk=review_id)
    review.is_hidden = True
    review.save(update_fields=["is_hidden", "updated_at"])
    return Response({"detail": "Review hidden.", "review": ReviewSerializer(review).data}, status=status.HTTP_200_OK)


# PUBLIC_INTERFACE
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdminRole])
def api_admin_unhide_review(request, review_id: int):
    """Admin-only: unhide a review (make public)."""
    review = get_object_or_404(Review.objects.select_related("item"), pk=review_id)
    review.is_hidden = False
    review.save(update_fields=["is_hidden", "updated_at"])
    return Response({"detail": "Review unhidden.", "review": ReviewSerializer(review).data}, status=status.HTTP_200_OK)
