from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from core.models import Item, WishlistEntry


class WishlistApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="u1", password="pass12345")
        self.item = Item.all_objects.create(
            title="Test Item",
            price=10.0,
            discount_price=None,
            category="S",
            label="P",
            slug="test-item",
            description="desc",
            image="test.jpg",
            active=True,
            track_inventory=False,
            stock_quantity=0,
        )

    def test_wishlist_requires_auth(self):
        resp = self.client.get("/api/wishlist/")
        self.assertEqual(resp.status_code, 401)

    def test_wishlist_add_prevents_duplicates(self):
        self.client.force_authenticate(user=self.user)

        r1 = self.client.post("/api/wishlist/add/", {"item_id": self.item.id}, format="json")
        self.assertIn(r1.status_code, (200, 201))

        r2 = self.client.post("/api/wishlist/add/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r2.status_code, 200)

        self.assertEqual(WishlistEntry.objects.filter(user=self.user, item=self.item).count(), 1)

    def test_wishlist_remove_is_idempotent(self):
        self.client.force_authenticate(user=self.user)

        # remove before add
        r1 = self.client.post("/api/wishlist/remove/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r1.status_code, 200)

        # add then remove
        self.client.post("/api/wishlist/add/", {"item_id": self.item.id}, format="json")
        r2 = self.client.post("/api/wishlist/remove/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r2.status_code, 200)

        self.assertEqual(WishlistEntry.objects.filter(user=self.user, item=self.item).count(), 0)
