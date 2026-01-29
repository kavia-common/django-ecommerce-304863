import pytest


@pytest.mark.django_db
def test_jwt_obtain_refresh_verify_and_protected_endpoint(
    api_client, user, user_password
):
    # Obtain
    resp = api_client.post(
        "/api/auth/jwt/create/",
        {"username": user.username, "password": user_password},
        format="json",
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access" in tokens and "refresh" in tokens

    access = tokens["access"]
    refresh = tokens["refresh"]

    # Verify
    verify_resp = api_client.post(
        "/api/auth/jwt/verify/", {"token": access}, format="json"
    )
    assert verify_resp.status_code == 200

    # Refresh
    refresh_resp = api_client.post(
        "/api/auth/jwt/refresh/", {"refresh": refresh}, format="json"
    )
    assert refresh_resp.status_code == 200
    refreshed = refresh_resp.json()
    assert "access" in refreshed and refreshed["access"]

    # Protected endpoint should reject without auth
    unauth = api_client.get("/api/orders/")
    assert unauth.status_code in (401, 403)

    # Protected endpoint should allow with auth
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    ok = api_client.get("/api/orders/")
    assert ok.status_code == 200
    assert isinstance(ok.json(), list)


@pytest.mark.django_db
def test_jwt_verify_rejects_invalid_token(api_client):
    bad = api_client.post(
        "/api/auth/jwt/verify/", {"token": "not-a-jwt"}, format="json"
    )
    assert bad.status_code == 401
