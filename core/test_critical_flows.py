from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Coupon, Item, Order, OrderItem, Payment, Review, WishlistEntry


def _make_item(*, slug: str, stock: int, track_inventory: bool = True) -> Item:
    # Use all_objects to bypass ActiveItemManager filtering in tests when needed.
    return Item.all_objects.create(
        title=f"Item {slug}",
        price=100.0,
        discount_price=None,
        category="S",
        label="P",
        slug=slug,
        description="desc",
        image="test.jpg",
        active=True,
        track_inventory=track_inventory,
        stock_quantity=stock,
    )


def _make_paid_order_with_item(*, user, item: Item, qty: int = 1, coupon: Coupon | None = None) -> Order:
    oi = OrderItem.objects.create(user=user, item=item, ordered=False, quantity=qty)
    order = Order.objects.create(user=user, ordered=False, ordered_date=timezone.now(), coupon=coupon)
    order.items.add(oi)
    # Simulate a payment finalization (without invoking Stripe).
    payment = Payment.objects.create(user=user, amount=order.get_total(), stripe_payment_intent_id="pi_test")
    # Mirror views._finalize_order_after_successful_payment logic (model methods are used there).
    Item.atomic_decrement_stock_for_order(order)
    order.items.all().update(ordered=True)
    order.ordered = True
    order.payment = payment
    try:
        order.transition_to(Order.OrderStatus.PLACED, actor=user)
    except Exception:
        pass
    order.save()
    return order


class JwtAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="jwt_u", password="pass12345")

    def test_token_obtain_refresh_verify_and_me(self):
        r = self.client.post("/api/auth/token/", {"username": "jwt_u", "password": "pass12345"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)

        access = r.data["access"]
        refresh = r.data["refresh"]

        # verify
        rv = self.client.post("/api/auth/token/verify/", {"token": access}, format="json")
        self.assertEqual(rv.status_code, 200)

        # protected /api/auth/me/ without auth
        r_me_anon = self.client.get("/api/auth/me/")
        self.assertEqual(r_me_anon.status_code, 401)

        # protected /api/auth/me/ with bearer
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        r_me = self.client.get("/api/auth/me/")
        self.assertEqual(r_me.status_code, 200)
        self.assertEqual(r_me.data["username"], "jwt_u")

        # refresh
        self.client.credentials()  # clear
        rr = self.client.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(rr.status_code, 200)
        self.assertIn("access", rr.data)


class RbacTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        User = get_user_model()
        self.admin_user = User.objects.create_user(username="admin", password="pass12345", is_staff=False)
        self.normal_user = User.objects.create_user(username="normal", password="pass12345")

        admin_group, _ = Group.objects.get_or_create(name="Admin")
        self.admin_user.groups.add(admin_group)

        self.item = _make_item(slug="rbac-item", stock=10)

    def _jwt_for(self, username: str, password: str) -> str:
        r = self.api.post("/api/auth/token/", {"username": username, "password": password}, format="json")
        self.assertEqual(r.status_code, 200)
        return r.data["access"]

    def test_admin_api_requires_admin_role(self):
        # normal user forbidden
        access = self._jwt_for("normal", "pass12345")
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        r = self.api.get("/api/admin/items/")
        self.assertEqual(r.status_code, 403)

        # admin allowed
        access_admin = self._jwt_for("admin", "pass12345")
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {access_admin}")
        r2 = self.api.get("/api/admin/items/")
        self.assertEqual(r2.status_code, 200)

    def test_manage_template_views_require_admin(self):
        # These are django session views, not JWT.
        c = Client()

        # anon should redirect to login (user_passes_test -> login_url)
        resp_anon = c.get("/manage/orders/")
        self.assertIn(resp_anon.status_code, (302, 301))

        # normal user should also redirect (fails user_passes_test)
        c.login(username="normal", password="pass12345")
        resp_normal = c.get("/manage/orders/")
        self.assertIn(resp_normal.status_code, (302, 301))

        # admin user should succeed
        c.logout()
        c.login(username="admin", password="pass12345")
        resp_admin = c.get("/manage/orders/")
        self.assertEqual(resp_admin.status_code, 200)


class InventoryAndCartTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="inv_u", password="pass12345")
        self.client = Client()

    def test_cannot_add_beyond_stock(self):
        item = _make_item(slug="stock1", stock=1, track_inventory=True)
        self.client.login(username="inv_u", password="pass12345")

        # first add ok -> cart qty 1
        r1 = self.client.get(f"/add-to-cart/{item.slug}/")
        self.assertIn(r1.status_code, (302, 301))
        oi = OrderItem.objects.get(user=self.user, item=item, ordered=False)
        self.assertEqual(oi.quantity, 1)

        # second add should be blocked and qty remains 1
        r2 = self.client.get(f"/add-to-cart/{item.slug}/")
        self.assertIn(r2.status_code, (302, 301))
        oi.refresh_from_db()
        self.assertEqual(oi.quantity, 1)

    def test_stock_validated_at_payment_and_atomic_decrement_on_finalize(self):
        item = _make_item(slug="stock2", stock=1, track_inventory=True)
        self.client.login(username="inv_u", password="pass12345")
        self.client.get(f"/add-to-cart/{item.slug}/")

        # create billing address quickly by setting directly (avoid form complexity)
        order = Order.objects.get(user=self.user, ordered=False)
        # PaymentView.get checks billing address exists; set it to bypass redirect
        from core.models import Address

        addr = Address.objects.create(
            user=self.user,
            street_address="s",
            apartment_address="a",
            country="US",
            zip="12345",
            address_type="B",
        )
        order.billing_address = addr
        order.save()

        # If stock becomes 0 before payment, the PaymentView should redirect to order-summary.
        Item.all_objects.filter(pk=item.pk).update(stock_quantity=0)
        r_pay_get = self.client.get("/payment/stripe/")
        # Should redirect due to ensure_can_fulfill failure
        self.assertIn(r_pay_get.status_code, (302, 301))

        # Restore stock for finalize simulation
        Item.all_objects.filter(pk=item.pk).update(stock_quantity=1)
        item.refresh_from_db()

        # Finalize via helper (simulates successful payment): stock decremented to 0 and never negative
        paid_order = _make_paid_order_with_item(user=self.user, item=item, qty=1)
        item.refresh_from_db()
        self.assertEqual(item.stock_quantity, 0)
        self.assertTrue(paid_order.ordered)

    def test_admin_inventory_adjust_prevents_negative_stock(self):
        api = APIClient()
        User = get_user_model()
        admin = User.objects.create_user(username="inv_admin", password="pass12345")
        Group.objects.get_or_create(name="Admin")[0].user_set.add(admin)
        item = _make_item(slug="stock3", stock=0, track_inventory=True)

        # login via JWT
        r = api.post("/api/auth/token/", {"username": "inv_admin", "password": "pass12345"}, format="json")
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

        resp = api.post("/api/admin/inventory/adjust/", {"item_id": item.id, "delta": -1}, format="json")
        self.assertEqual(resp.status_code, 400)

        item.refresh_from_db()
        self.assertEqual(item.stock_quantity, 0)


class OrderLifecycleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="life_admin", password="pass12345")
        Group.objects.get_or_create(name="Admin")[0].user_set.add(self.admin)
        self.user = User.objects.create_user(username="life_user", password="pass12345")

        self.item = _make_item(slug="life-item", stock=5, track_inventory=True)

        self.api = APIClient()
        r = self.api.post("/api/auth/token/", {"username": "life_admin", "password": "pass12345"}, format="json")
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")

    def test_reject_invalid_transitions_and_unpaid_cart(self):
        # unpaid cart cannot be shipped/delivered
        oi = OrderItem.objects.create(user=self.user, item=self.item, ordered=False, quantity=1)
        cart = Order.objects.create(user=self.user, ordered=False, ordered_date=timezone.now())
        cart.items.add(oi)

        r = self.api.post(f"/api/admin/orders/{cart.id}/transition/", {"new_status": "shipped"}, format="json")
        self.assertEqual(r.status_code, 400)

        # Paid order can transition placed -> shipped -> delivered, but not backwards
        paid = _make_paid_order_with_item(user=self.user, item=self.item, qty=1)
        paid.refresh_from_db()
        self.assertEqual(paid.status, Order.OrderStatus.PLACED)

        r_ship = self.api.post(f"/api/admin/orders/{paid.id}/transition/", {"new_status": "shipped"}, format="json")
        self.assertEqual(r_ship.status_code, 200)
        paid.refresh_from_db()
        self.assertEqual(paid.status, Order.OrderStatus.SHIPPED)
        self.assertIsNotNone(paid.shipped_at)

        r_del = self.api.post(f"/api/admin/orders/{paid.id}/transition/", {"new_status": "delivered"}, format="json")
        self.assertEqual(r_del.status_code, 200)
        paid.refresh_from_db()
        self.assertEqual(paid.status, Order.OrderStatus.DELIVERED)
        self.assertIsNotNone(paid.delivered_at)

        # invalid backward transition
        r_bad = self.api.post(f"/api/admin/orders/{paid.id}/transition/", {"new_status": "shipped"}, format="json")
        self.assertEqual(r_bad.status_code, 400)


class StripeFlowsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="stripe_u", password="pass12345")
        self.item = _make_item(slug="stripe-item", stock=2, track_inventory=True)

    @patch("stripe.PaymentIntent.retrieve")
    def test_payment_view_requires_succeeded_payment_intent(self, mock_retrieve):
        """
        PaymentView.post will only finalize when PaymentIntent status is succeeded.
        """
        c = Client()
        c.login(username="stripe_u", password="pass12345")
        c.get(f"/add-to-cart/{self.item.slug}/")

        from core.models import Address

        order = Order.objects.get(user=self.user, ordered=False)
        addr = Address.objects.create(
            user=self.user,
            street_address="s",
            apartment_address="a",
            country="US",
            zip="12345",
            address_type="B",
        )
        order.billing_address = addr
        order.save()

        # Not succeeded => should NOT finalize and should redirect
        mock_retrieve.return_value = {"id": "pi_x", "status": "requires_payment_method", "client_secret": "sec"}
        resp = c.post(
            "/payment/stripe/",
            data={"payment_intent_id": "pi_x", "save": False, "use_default": False, "stripeToken": ""},
        )
        self.assertIn(resp.status_code, (302, 301))
        order.refresh_from_db()
        self.assertFalse(order.ordered)

        # succeeded => finalize and decrement stock
        mock_retrieve.return_value = {"id": "pi_succ", "status": "succeeded", "client_secret": "sec"}
        resp2 = c.post(
            "/payment/stripe/",
            data={"payment_intent_id": "pi_succ", "save": False, "use_default": False, "stripeToken": ""},
        )
        self.assertIn(resp2.status_code, (302, 301))
        order.refresh_from_db()
        self.assertTrue(order.ordered)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_quantity, 1)

    def test_webhook_idempotency_and_safe_processing(self):
        """
        stripe_webhook:
          - processes payment_intent.succeeded and creates Payment with stripe_event_id
          - is idempotent: second delivery with same event id does nothing
          - decrements inventory once
        """
        # Create an unpaid cart
        oi = OrderItem.objects.create(user=self.user, item=self.item, ordered=False, quantity=1)
        order = Order.objects.create(user=self.user, ordered=False, ordered_date=timezone.now())
        order.items.add(oi)

        payload = {
            "id": "evt_1",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_webhook", "client_secret": "cs", "metadata": {"order_id": str(order.id)}}},
        }

        from django.test import Client as DjangoClient

        c = DjangoClient()

        # Patch Stripe signature verification and event construction to return our dict-like event.
        with patch("stripe.Webhook.construct_event", return_value=payload):
            r1 = c.post(
                "/stripe/webhook/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )
            self.assertEqual(r1.status_code, 200)

        order.refresh_from_db()
        self.assertTrue(order.ordered)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_quantity, 1)
        self.assertTrue(Payment.objects.filter(stripe_event_id="evt_1").exists())

        # Repeat same event id => no additional decrement or new Payment
        with patch("stripe.Webhook.construct_event", return_value=payload):
            r2 = c.post(
                "/stripe/webhook/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )
            self.assertEqual(r2.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_quantity, 1)
        self.assertEqual(Payment.objects.filter(stripe_event_id="evt_1").count(), 1)


class WishlistApiCriticalTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.user = get_user_model().objects.create_user(username="wl_u", password="pass12345")
        self.item = _make_item(slug="wl-item", stock=0, track_inventory=False)

    def test_list_add_remove_and_no_duplicates(self):
        # unauth
        r0 = self.api.get("/api/wishlist/")
        self.assertEqual(r0.status_code, 401)

        self.api.force_authenticate(user=self.user)

        # empty list
        r1 = self.api.get("/api/wishlist/")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["count"], 0)

        # add
        r2 = self.api.post("/api/wishlist/add/", {"item_id": self.item.id}, format="json")
        self.assertIn(r2.status_code, (200, 201))

        # duplicate add safe
        r3 = self.api.post("/api/wishlist/add/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(WishlistEntry.objects.filter(user=self.user, item=self.item).count(), 1)

        # list shows item
        r4 = self.api.get("/api/wishlist/")
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.data["count"], 1)

        # remove idempotent
        r5 = self.api.post("/api/wishlist/remove/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r5.status_code, 200)
        r6 = self.api.post("/api/wishlist/remove/", {"item_id": self.item.id}, format="json")
        self.assertEqual(r6.status_code, 200)


class ReviewsCriticalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="rev_u", password="pass12345")
        self.other = User.objects.create_user(username="rev_other", password="pass12345")
        self.admin = User.objects.create_user(username="rev_admin", password="pass12345")
        Group.objects.get_or_create(name="Admin")[0].user_set.add(self.admin)

        self.api = APIClient()
        self.item = _make_item(slug="rev-item", stock=10, track_inventory=True)

    def test_only_purchasers_can_review_and_one_review_per_user(self):
        # attempt without purchase
        self.api.force_authenticate(user=self.user)
        r_forbidden = self.api.post(
            f"/api/reviews/items/{self.item.id}/me/",
            {"rating": 5, "title": "t", "body": "this is a sufficiently long review"},
            format="json",
        )
        self.assertEqual(r_forbidden.status_code, 403)

        # purchase then create review
        _make_paid_order_with_item(user=self.user, item=self.item, qty=1)

        r1 = self.api.post(
            f"/api/reviews/items/{self.item.id}/me/",
            {"rating": 5, "title": "t", "body": "this is a sufficiently long review"},
            format="json",
        )
        self.assertIn(r1.status_code, (200, 201))
        self.assertEqual(Review.objects.filter(user=self.user, item=self.item).count(), 1)

        # upsert updates rather than creating a second
        r2 = self.api.post(
            f"/api/reviews/items/{self.item.id}/me/",
            {"rating": 4, "title": "t2", "body": "this is another sufficiently long review"},
            format="json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(Review.objects.filter(user=self.user, item=self.item).count(), 1)
        self.assertEqual(Review.objects.get(user=self.user, item=self.item).rating, 4)

    def test_rating_validation(self):
        _make_paid_order_with_item(user=self.user, item=self.item, qty=1)
        self.api.force_authenticate(user=self.user)

        r_bad = self.api.post(
            f"/api/reviews/items/{self.item.id}/me/",
            {"rating": 6, "title": "t", "body": "this is a sufficiently long review"},
            format="json",
        )
        self.assertEqual(r_bad.status_code, 400)

    def test_visibility_and_admin_hide_unhide(self):
        _make_paid_order_with_item(user=self.user, item=self.item, qty=1)
        self.api.force_authenticate(user=self.user)

        r = self.api.post(
            f"/api/reviews/items/{self.item.id}/me/",
            {"rating": 5, "title": "t", "body": "this is a sufficiently long review"},
            format="json",
        )
        self.assertIn(r.status_code, (200, 201))
        review_id = r.data["review"]["id"]

        # public list shows it
        self.api.force_authenticate(user=None)
        r_list = self.api.get(f"/api/reviews/items/{self.item.id}/")
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(r_list.data["reviews_count"], 1)

        # admin hides it
        self.api.force_authenticate(user=self.admin)
        r_hide = self.api.post(f"/api/reviews/{review_id}/hide/", {}, format="json")
        self.assertEqual(r_hide.status_code, 200)

        # public list now hides it
        self.api.force_authenticate(user=None)
        r_list2 = self.api.get(f"/api/reviews/items/{self.item.id}/")
        self.assertEqual(r_list2.status_code, 200)
        self.assertEqual(r_list2.data["reviews_count"], 0)

        # admin unhide
        self.api.force_authenticate(user=self.admin)
        r_unhide = self.api.post(f"/api/reviews/{review_id}/unhide/", {}, format="json")
        self.assertEqual(r_unhide.status_code, 200)

        self.api.force_authenticate(user=None)
        r_list3 = self.api.get(f"/api/reviews/items/{self.item.id}/")
        self.assertEqual(r_list3.data["reviews_count"], 1)


class CouponsCriticalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cp_u", password="pass12345")
        self.item = _make_item(slug="cp-item", stock=999, track_inventory=False)
        self.oi = OrderItem.objects.create(user=self.user, item=self.item, ordered=False, quantity=1)
        self.order = Order.objects.create(user=self.user, ordered=False, ordered_date=timezone.now())
        self.order.items.add(self.oi)

    def test_percent_and_fixed_discounts_and_totals(self):
        c_pct = Coupon.objects.create(code="P10", discount_type=Coupon.DiscountType.PERCENT, percent_off="10.00", active=True)
        self.order.apply_coupon(c_pct, user=self.user)
        self.order.save()
        self.assertAlmostEqual(self.order.get_total(), 90.0, places=2)

        self.order.remove_coupon()
        self.order.save()
        c_fix = Coupon.objects.create(code="F5", discount_type=Coupon.DiscountType.FIXED, fixed_amount_off="5.00", active=True)
        self.order.apply_coupon(c_fix, user=self.user)
        self.order.save()
        self.assertAlmostEqual(self.order.get_total(), 95.0, places=2)

    def test_validity_windows_and_min_order(self):
        now = timezone.now()
        c_win = Coupon.objects.create(
            code="WIN",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            starts_at=now + timezone.timedelta(days=1),
            ends_at=now + timezone.timedelta(days=2),
            active=True,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c_win, user=self.user)

        c_min = Coupon.objects.create(
            code="MIN200",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            min_order_total="200.00",
            active=True,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c_min, user=self.user)

    def test_global_and_per_user_limits_enforced(self):
        # global limit reached
        c_glob = Coupon.objects.create(
            code="GLOB1",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            active=True,
            max_redemptions=1,
            redemption_count=1,
        )
        with self.assertRaises(ValueError):
            self.order.apply_coupon(c_glob, user=self.user)

        # per user limit reached using CouponRedemption via paid order
        from core.models import CouponRedemption

        c_u = Coupon.objects.create(
            code="U1",
            discount_type=Coupon.DiscountType.FIXED,
            fixed_amount_off="5.00",
            active=True,
            max_uses_per_user=1,
        )
        paid = Order.objects.create(user=self.user, ordered=True, ordered_date=timezone.now(), coupon=c_u)
        CouponRedemption.objects.create(coupon=c_u, user=self.user, order=paid)

        with self.assertRaises(ValueError):
            self.order.apply_coupon(c_u, user=self.user)

    def test_apply_remove_flows_via_template_views(self):
        """
        Verify /add-coupon/ and /remove-coupon/ template flows mutate the active order.
        """
        c = Client()
        c.login(username="cp_u", password="pass12345")

        coupon = Coupon.objects.create(code="T5", discount_type=Coupon.DiscountType.FIXED, fixed_amount_off="5.00", active=True)

        r_apply = c.post("/add-coupon/", data={"code": coupon.code})
        self.assertIn(r_apply.status_code, (302, 301))
        self.order.refresh_from_db()
        self.assertEqual(self.order.coupon_id, coupon.id)

        r_remove = c.get("/remove-coupon/")
        self.assertIn(r_remove.status_code, (302, 301))
        self.order.refresh_from_db()
        self.assertIsNone(self.order.coupon)
