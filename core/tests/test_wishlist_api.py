import pytest


@pytest.mark.django_db
def test_wishlist_requires_auth(api_client):
    resp = api_client.get("/api/wishlist/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_wishlist_add_list_remove_idempotent(api_client, item_factory, auth_headers_for_user):
    item = item_factory()

    # Add first time => 201
    resp = api_client.post("/api/wishlist/", {"item_id": item.id}, format="json", **auth_headers_for_user)
    assert resp.status_code == 201
    assert resp.json()["item_id"] == item.id

    # Add again => 200 (idempotent)
    resp2 = api_client.post("/api/wishlist/", {"item_id": item.id}, format="json", **auth_headers_for_user)
    assert resp2.status_code == 200
    assert resp2.json()["item_id"] == item.id

    # List should include exactly one
    listing = api_client.get("/api/wishlist/", **auth_headers_for_user)
    assert listing.status_code == 200
    data = listing.json()
    # Pagination may be enabled; handle both shapes.
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert len(items) == 1
    assert items[0]["item_id"] == item.id

    # Remove existing => 204
    d1 = api_client.delete(f"/api/wishlist/{item.id}/", **auth_headers_for_user)
    assert d1.status_code == 204

    # Remove again => still 204 (idempotent)
    d2 = api_client.delete(f"/api/wishlist/{item.id}/", **auth_headers_for_user)
    assert d2.status_code == 204


@pytest.mark.django_db
def test_wishlist_user_scoped(api_client, item_factory, obtain_jwt_tokens, user, user_password):
    item = item_factory()

    # Second user
    from django.contrib.auth.models import User

    other = User.objects.create(username="other_user")
    other.set_password("other_pass")
    other.save()

    tokens_other = obtain_jwt_tokens(other, "other_pass")
    hdr_other = {"HTTP_AUTHORIZATION": f"Bearer {tokens_other['access']}"}

    hdr_user = {"HTTP_AUTHORIZATION": f"Bearer {obtain_jwt_tokens(user, user_password)['access']}"}

    api_client.post("/api/wishlist/", {"item_id": item.id}, format="json", **hdr_user)

    # Other user's list must be empty
    listing = api_client.get("/api/wishlist/", **hdr_other)
    assert listing.status_code == 200
    data = listing.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert items == []
