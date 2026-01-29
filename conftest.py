from __future__ import annotations

import io
import os
import uuid
from typing import Callable, Dict, Tuple

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from core.models import Coupon, Item, Order, OrderItem, Review


@pytest.fixture(autouse=True)
def _configure_test_media_root(settings, tmp_path):
    """
    Ensure ImageField writes go to a temp directory so tests don't pollute the repo.
    """
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def django_client():
    """
    Django test client for template-based endpoints (/add-coupon/, etc).
    """
    from django.test import Client

    return Client()


@pytest.fixture
def make_test_image_file() -> Callable[[str], SimpleUploadedFile]:
    """
    Return a callable that generates a valid small PNG upload for Item.image.
    """

    def _make(name: str = "test.png") -> SimpleUploadedFile:
        buf = io.BytesIO()
        img = Image.new("RGB", (8, 8), color=(255, 0, 0))
        img.save(buf, format="PNG")
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), content_type="image/png")

    return _make


@pytest.fixture
def user_password() -> str:
    return "pass-12345"


@pytest.fixture
def user(db, user_password) -> User:
    u = User.objects.create(username=f"user_{uuid.uuid4().hex[:8]}", email="user@example.com")
    u.set_password(user_password)
    u.save()
    return u


@pytest.fixture
def admin_user(db, user_password) -> User:
    u = User.objects.create(username=f"admin_{uuid.uuid4().hex[:8]}", email="admin@example.com")
    u.set_password(user_password)
    u.is_staff = True
    u.save()
    return u


@pytest.fixture
def admin_group(db) -> Group:
    """
    Ensure the 'Admin' group exists (migration creates it, but tests should be resilient).
    """
    grp, _ = Group.objects.get_or_create(name="Admin")
    return grp


@pytest.fixture
def admin_user_in_group(admin_user, admin_group) -> User:
    admin_user.groups.add(admin_group)
    return admin_user


@pytest.fixture
def obtain_jwt_tokens(api_client) -> Callable[[User, str], Dict[str, str]]:
    """
    Obtain JWT tokens via the real SimpleJWT endpoint to cover that surface area.
    """

    def _obtain(user_obj: User, password: str) -> Dict[str, str]:
        resp = api_client.post(
            "/api/auth/jwt/create/",
            {"username": user_obj.username, "password": password},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert "access" in data and "refresh" in data
        return {"access": data["access"], "refresh": data["refresh"]}

    return _obtain


@pytest.fixture
def auth_headers_for_user(obtain_jwt_tokens, user, user_password) -> Dict[str, str]:
    tokens = obtain_jwt_tokens(user, user_password)
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access']}"}


@pytest.fixture
def auth_headers_for_admin(obtain_jwt_tokens, admin_user_in_group, user_password) -> Dict[str, str]:
    tokens = obtain_jwt_tokens(admin_user_in_group, user_password)
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access']}"}


@pytest.fixture
def item_factory(db, make_test_image_file) -> Callable[..., Item]:
    def _make(**kwargs) -> Item:
        defaults = dict(
            title=f"Item {uuid.uuid4().hex[:6]}",
            price=10.0,
            discount_price=None,
            category="S",
            label="P",
            slug=f"item-{uuid.uuid4().hex[:10]}",
            description="desc",
            image=make_test_image_file(),
            sku=f"SKU-{uuid.uuid4().hex[:10]}",
            is_active=True,
            low_stock_threshold=0,
            stock_on_hand=10,
            stock_reserved=0,
        )
        defaults.update(kwargs)
        return Item.objects.create(**defaults)

    return _make


@pytest.fixture
def order_factory(db) -> Callable[..., Tuple[Order, OrderItem]]:
    """
    Create an Order with one OrderItem. Caller can pass:
      - user
      - item
      - quantity
      - status
      - ordered
    """

    def _make(*, user: User, item: Item, quantity: int = 1, status: str = Order.Status.CREATED, ordered: bool = False):
        oi = OrderItem.objects.create(user=user, item=item, quantity=quantity, ordered=ordered)
        order = Order.objects.create(
            user=user,
            ordered=ordered,
            status=status,
            ordered_date=timezone.now(),
        )
        order.items.add(oi)
        return order, oi

    return _make


@pytest.fixture
def coupon_factory(db) -> Callable[..., Coupon]:
    def _make(**kwargs) -> Coupon:
        defaults = dict(code=f"CODE{uuid.uuid4().hex[:6]}", amount=5.0)
        defaults.update(kwargs)
        return Coupon.objects.create(**defaults)

    return _make


@pytest.fixture
def review_factory(db) -> Callable[..., Review]:
    def _make(**kwargs) -> Review:
        defaults = dict(
            user=kwargs.pop("user"),
            item=kwargs.pop("item"),
            rating=5,
            title="Great",
            body="Loved it",
            is_approved=False,
        )
        defaults.update(kwargs)
        return Review.objects.create(**defaults)

    return _make
