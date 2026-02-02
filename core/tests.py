from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from django.utils import timezone

from core.models import Item, WishlistEntry, Coupon, Order, OrderItem, CouponRedemption


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


class CouponDiscountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cu1", password="pass12345")
        self.item = Item.all_objects.create(
            title="Item",
            price=100.0,
            discount_price=None,
            category="S",
            label="P",
            slug="coupon-item",
            description="desc",
            image="test.jpg",
            active=True,
            track_inventory=False,
            stock_quantity=0,
        )
        self.order_item = OrderItem.objects.create(user=self.user, item=self.item, ordered=False, quantity=1)
        self.order = Order.objects.create(user=self.user, ordered=False, ordered_date=timezone.now())
        self.order.items.add(self.order_item)

    def test_percent_coupon_applies(self):
        c = Coupon.objects.create(code="P10", discount_type=Coupon.DiscountType.PERCENT, percent_off="10.00", active=True)
        self.order.apply_coupon(c, user=self.user)
        self.order.save()
        self.assertAlmostEqual(self.order.get_coupon_discount(), 10.0, places=2)
        self.assertAlmostEqual(self.order.get_total(), 90.0, places=2)

    def test_fixed_coupon_applies_and_caps_at_subtotal(self):
        c = Coupon.objects.create(code="F200", discount_type=Coupon.DiscountType.FIXED, fixed_amount_off="200.00", active=True)
        self.order.apply_coupon(c, user=self.user)
        self.order.save()
        self.assertAlmostEqual(self.order.get_total(), 0.0, places=2)

    def test_min_order_total_blocks(self):
        c = Coupon.objects.create(
            code="MIN200",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            min_order_total="200.00",
            active=True,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c, user=self.user)

    def test_validity_window_blocks(self):
        now = timezone.now()
        c = Coupon.objects.create(
            code="WIN",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            starts_at=now + timezone.timedelta(days=1),
            ends_at=now + timezone.timedelta(days=2),
            active=True,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c, user=self.user)

    def test_disabled_blocks(self):
        c = Coupon.objects.create(code="OFF", discount_type=Coupon.DiscountType.FIXED, fixed_amount_off="5.00", active=False)
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c, user=self.user)

    def test_remove_coupon_is_idempotent(self):
        c = Coupon.objects.create(code="REM", discount_type=Coupon.DiscountType.FIXED, fixed_amount_off="5.00", active=True)
        self.order.apply_coupon(c, user=self.user)
        self.order.save()
        self.order.remove_coupon()
        self.order.save()
        self.order.remove_coupon()
        self.order.save()
        self.assertIsNone(self.order.coupon)
        self.assertAlmostEqual(self.order.get_total(), 100.0, places=2)

    def test_global_redemption_limit_enforced_on_apply(self):
        c = Coupon.objects.create(
            code="GLOB1",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            active=True,
            max_redemptions=1,
            redemption_count=1,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c, user=self.user)

    def test_per_user_limit_enforced_on_apply(self):
        c = Coupon.objects.create(
            code="U1",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            active=True,
            max_uses_per_user=1,
        )
        # record a past successful redemption
        paid_order = Order.objects.create(user=self.user, ordered=True, ordered_date=timezone.now(), coupon=c)
        CouponRedemption.objects.create(coupon=c, user=self.user, order=paid_order)

        with self.assertRaises(ValueError):
            self.order.apply_coupon(c, user=self.user)
