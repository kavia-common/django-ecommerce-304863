import pytest

from core.models import Review


@pytest.mark.django_db
def test_reviews_public_list_only_approved(api_client, item_factory, user, review_factory):
    item = item_factory()
    unapproved = review_factory(user=user, item=item, rating=5, is_approved=False)
    approved = review_factory(user=user, item=item, rating=4, is_approved=True)

    resp = api_client.get("/api/reviews/")
    assert resp.status_code == 200
    data = resp.json()
    ids = {r["id"] for r in data}
    assert approved.id in ids
    assert unapproved.id not in ids


@pytest.mark.django_db
def test_review_create_requires_auth(api_client, item_factory):
    item = item_factory()
    resp = api_client.post("/api/reviews/", {"item_id": item.id, "rating": 5, "body": "Hi"}, format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_review_owner_create_unique_and_admin_approve_affects_product_aggregates(
    api_client,
    item_factory,
    auth_headers_for_user,
    auth_headers_for_admin,
):
    item = item_factory()

    create = api_client.post(
        "/api/reviews/",
        {"item_id": item.id, "rating": 5, "title": "t", "body": "b"},
        format="json",
        **auth_headers_for_user,
    )
    assert create.status_code == 201, create.content
    review_id = create.json()["id"]

    # Second review for same (user,item) should be blocked (unique constraint)
    dup = api_client.post(
        "/api/reviews/",
        {"item_id": item.id, "rating": 4, "title": "t2", "body": "b2"},
        format="json",
        **auth_headers_for_user,
    )
    assert dup.status_code == 400

    # Not visible publicly until approved
    public_before = api_client.get("/api/reviews/")
    assert review_id not in {r["id"] for r in public_before.json()}

    # Admin approves
    appr = api_client.post(f"/api/reviews/{review_id}/approve/", {}, format="json", **auth_headers_for_admin)
    assert appr.status_code == 200
    assert appr.json()["is_approved"] is True

    # Now visible publicly
    public_after = api_client.get("/api/reviews/")
    assert review_id in {r["id"] for r in public_after.json()}

    # Nested product reviews endpoint should return approved reviews only
    nested = api_client.get(f"/api/products/{item.id}/reviews/")
    assert nested.status_code == 200
    nested_data = nested.json()
    nested_results = nested_data["results"] if isinstance(nested_data, dict) and "results" in nested_data else nested_data
    assert any(r["id"] == review_id for r in nested_results)

    # Product aggregates should reflect approved review
    prod = api_client.get(f"/api/products/{item.id}/")
    assert prod.status_code == 200
    p = prod.json()
    assert p["review_count"] == 1
    assert abs(float(p["average_rating"]) - 5.0) < 1e-6


@pytest.mark.django_db
def test_user_editing_approved_review_forces_remoderation(api_client, item_factory, user, obtain_jwt_tokens):
    item = item_factory()

    # Create a review directly as approved
    review = Review.objects.create(user=user, item=item, rating=5, title="t", body="b", is_approved=True)

    tokens = obtain_jwt_tokens(user, "pass-12345") if False else None  # keep lint quiet; we use real auth below

    # Obtain a real token for this user by setting a password
    user.set_password("pw")
    user.save()
    access = obtain_jwt_tokens(user, "pw")["access"]
    hdr = {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    # PATCH triggers perform_update logic; for non-admin editing approved -> becomes unapproved
    resp = api_client.patch(f"/api/reviews/{review.id}/", {"body": "edited", "item_id": item.id}, format="json", **hdr)
    assert resp.status_code == 200

    review.refresh_from_db()
    assert review.body == "edited"
    assert review.is_approved is False


@pytest.mark.django_db
def test_user_cannot_delete_approved_review(api_client, item_factory, user):
    # Prepare approved review
    user.set_password("pw")
    user.save()

    item = item_factory()
    review = Review.objects.create(user=user, item=item, rating=5, title="t", body="b", is_approved=True)

    # Authenticate
    from rest_framework.test import APIClient

    client = APIClient()
    tok = client.post("/api/auth/jwt/create/", {"username": user.username, "password": "pw"}, format="json").json()
    hdr = {"HTTP_AUTHORIZATION": f"Bearer {tok['access']}"}

    resp = client.delete(f"/api/reviews/{review.id}/", **hdr)
    assert resp.status_code == 403
