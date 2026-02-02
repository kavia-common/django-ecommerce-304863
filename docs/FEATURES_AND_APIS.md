# Features and APIs

## Overview

This document describes the major features in the codebase and catalogs the relevant API endpoints and template routes. It is intentionally grounded in the implementation details found in `core/models.py`, `core/views.py`, and the DRF API modules.

## Conventions

### Authentication

- Template routes use session auth (`django-allauth`).
- `/api/**` routes use JWT by default (DRF + SimpleJWT).
- Admin-only APIs require the Admin role (Admin group, staff, or superuser).

### Money

Order totals are represented as floats for legacy/template compatibility. Internally, coupon calculations convert values to `Decimal` for correct rounding and then return float totals.

## Authentication APIs

### JWT endpoints

Mounted in `djecommerce/urls.py`:

- `POST /api/auth/token/`
- `POST /api/auth/token/refresh/`
- `POST /api/auth/token/verify/`
- `GET /api/auth/me/` (JWT-protected identity endpoint)

## Product management

### Models and fields

#### Category (`core.models.Category`)

Key fields:

- `name` (string)
- `slug` (unique)
- `active` (boolean)
- `created_at`, `updated_at`

Behavior:

- Categories can be deactivated (`active=false`), but are still visible to admin tooling.

#### Item (`core.models.Item`)

The Item model contains both legacy and modernized fields.

Key fields:

- `title`
- `price` (non-negative)
- `discount_price` (nullable, non-negative)
- `slug`
- `description`
- `image` (legacy image)
- `primary_image` (preferred, optional)
- `gallery` (JSON list, optional; falls back to text field if JSONField unavailable)
- `sku` (unique; used for inventory/product management)
- `active` (boolean; controls storefront visibility)
- `track_inventory` (boolean; if false, item is treated as always available)
- `stock_quantity` (non-negative integer)

Active flag behavior:

- Storefront queries use `Item.objects`, which is an `ActiveItemManager` that filters to `active=True`.
- Admin/ops use `Item.all_objects` to include inactive items.

### Storefront (template) routes

- `GET /` product listing
- `GET /product/<slug>/` product detail

The product detail view only allows active items via its default queryset (and because `Item.objects` filters to active).

### Admin product CRUD APIs (`/api/admin/products/**`)

These endpoints are implemented in `core/api_admin_products.py` and mounted in `djecommerce/urls.py`.

All require JWT + Admin role.

#### Categories

- `GET /api/admin/products/categories/` list categories (including inactive)
- `POST /api/admin/products/categories/` create category
- `GET /api/admin/products/categories/<category_id>/` retrieve
- `PUT/PATCH /api/admin/products/categories/<category_id>/` update
- `DELETE /api/admin/products/categories/<category_id>/` delete

Example: create category

```bash
curl -s -X POST http://127.0.0.1:8000/api/admin/products/categories/ \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Shoes","slug":"shoes","active":true}'
```

#### Items

- `GET /api/admin/products/items/` list items (including inactive)
- `POST /api/admin/products/items/` create item
- `GET /api/admin/products/items/<item_id>/` retrieve
- `PUT/PATCH /api/admin/products/items/<item_id>/` update
- `DELETE /api/admin/products/items/<item_id>/` delete

Soft-deactivate:

- `POST /api/admin/products/items/<item_id>/deactivate/` sets `active=false`

Inventory endpoints (see inventory section) are also under `/api/admin/products/items/<item_id>/inventory/`.

## Inventory tracking

## Overview

Inventory is tracked on `Item` using:

- `track_inventory`
- `stock_quantity`

If inventory tracking is enabled, the code enforces stock availability across the storefront checkout flow and prevents overselling.

### Storefront enforcement

- When adding to cart (`/add-to-cart/<slug>/`), the view prevents adding items beyond available stock if `track_inventory` is true.
- The checkout and payment pages re-validate quantities immediately before proceeding.
- Stock is decremented only after payment is confirmed (synchronous PaymentIntent confirmation or webhook event).

### Atomic decrement on successful payment

The core method is:

- `Item.atomic_decrement_stock_for_order(order)`

This method:

- locks item rows with `select_for_update()`
- validates each order item’s requested quantity against current `stock_quantity`
- decrements using `F()` expressions inside a transaction

The order finalization function shared by payment flows is:

- `core.views._finalize_order_after_successful_payment(order=..., user=..., payment=...)`

### Admin inventory APIs

There are two admin inventory adjustment surfaces:

1) Legacy endpoint (admin-only):
- `POST /api/admin/inventory/adjust/`

Request:

```json
{"item_id": 123, "delta": -2}
```

Behavior:
- locks the item row
- prevents negative stock (returns `400` if it would go below zero)

2) Product management inventory endpoint (admin-only):
- `GET /api/admin/products/items/<item_id>/inventory/`
- `POST /api/admin/products/items/<item_id>/inventory/` with `{"delta": <int>}`

## Order lifecycle

### Status model

Orders use an explicit status enum:

- `placed`
- `shipped`
- `delivered`

This is implemented as `Order.OrderStatus` in `core/models.py` and stored in `Order.status`.

### Timestamps

The model maintains milestone timestamps:

- `placed_at`
- `shipped_at`
- `delivered_at`

Additionally, the legacy boolean flags remain for backwards compatibility:

- `being_delivered`
- `received`

The model synchronizes legacy flags from the new status in `Order.transition_to()` / `Order.sync_legacy_flags_from_status()`.

### Valid transitions

Valid transitions are linear:

- placed → shipped → delivered

Backwards transitions are rejected.

Additionally, unpaid carts (`ordered=False`) cannot transition to shipped/delivered (defense in depth).

### Template routes

User order history:

- `GET /my/orders/` (lists paid orders for logged-in user)

Admin operations views:

- `GET /manage/orders/` (admin-only)
- `GET /manage/orders/<order_id>/transition/` (admin-only form)
- `POST /manage/orders/<order_id>/transition/` (admin-only transition action)

### Admin order APIs (`/api/admin/orders/**`)

Mounted in `core/api_views.py` and `core/urls.py`:

- `GET /api/admin/orders/` list all orders
- `GET /api/admin/orders/<order_id>/` details + status + history
- `POST /api/admin/orders/<order_id>/transition/` transition status

Example: transition an order to shipped

```bash
curl -s -X POST http://127.0.0.1:8000/api/admin/orders/123/transition/ \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"new_status":"shipped"}'
```

Response includes `status`, `status_display`, timestamps, and a `history` array.

## Payments (Stripe)

## Overview

Payments are integrated with Stripe. The project supports:

- Preferred flow: Stripe PaymentIntents with client-side confirmation (Stripe.js)
- Fallback flow: legacy token → Charge flow

Stock decrement and order finalization happen only after Stripe indicates payment success.

### PaymentIntent test-mode flow

#### Server-side: create PaymentIntent

`PaymentView.get` creates a PaymentIntent:

- amount: `order.get_total() * 100` in USD cents
- `automatic_payment_methods={"enabled": True}`
- `metadata={"order_id": ..., "user_id": ...}`
- `idempotency_key=f"order_{order.id}_pi_create"`

It then passes the `client_secret` into the `payment.html` template.

#### Client-side: confirm card payment

In `templates/payment.html`, if a client secret is present, the code calls:

- `stripe.confirmCardPayment(clientSecret, { payment_method: { card } })`

On success, it POSTs `payment_intent_id` back to `PaymentView.post`.

#### Server-side: finalize only if succeeded

`PaymentView.post` retrieves the PaymentIntent and requires:

- `pi["status"] == "succeeded"`

Only then does it create a `Payment` record and finalize the order.

### Webhook flow

Webhook endpoint:

- `POST /stripe/webhook/` (mounted in `core/urls.py`)

#### Signature verification

- If `settings.STRIPE_WEBHOOK_SECRET` is set (non-empty), the handler uses `stripe.Webhook.construct_event` to validate the signature.
- If the secret is missing/empty, the handler attempts to parse an unsigned payload (development convenience). This is not recommended for production.

#### Event types processed

The handler currently processes:

- `payment_intent.succeeded`
- `payment_intent.payment_failed` (records the event for idempotency)

Other event types return `200 OK` without action.

#### Idempotency behavior

Idempotency is implemented by storing the Stripe event id in:

- `Payment.stripe_event_id` (unique field)

If an event with the same id is delivered again, the handler returns `200` and does not re-finalize or decrement inventory.

#### How the webhook links to an order

The handler expects:

- `event["data"]["object"]["metadata"]["order_id"]`

If the PaymentIntent metadata does not include an order id, the handler does nothing and returns `200`.

### Testing with Stripe CLI (if available)

If you have the Stripe CLI installed, you can:

1) Log in:

```bash
stripe login
```

2) Forward events to your local server:

```bash
stripe listen --forward-to http://127.0.0.1:8000/stripe/webhook/
```

3) Use the displayed signing secret as your `STRIPE_TEST_WEBHOOK_SECRET`.

4) Trigger events:

```bash
stripe trigger payment_intent.succeeded
```

### Test cards

In test mode, Stripe supports standard test cards such as:

- `4242 4242 4242 4242` with any future expiry and any CVC

(Use only in test mode.)

## Wishlist

### Model behavior

Wishlist entries are stored in `core.models.WishlistEntry`:

- explicit model (not a plain M2M)
- unique constraint on `(user, item)` prevents duplicates
- intended to be idempotent and safe for repeated add/remove calls

### Template routes

- `GET /wishlist/` user wishlist page
- `GET /wishlist/toggle/<slug>/` toggle wishlist membership for an item

### API endpoints (`/api/wishlist/**`)

Implemented in `core/api_wishlist.py` and mounted in `core/urls.py`:

- `GET /api/wishlist/` list current user’s wishlist
- `POST /api/wishlist/add/` add item
- `POST /api/wishlist/remove/` remove item (idempotent)

Example: add to wishlist

```bash
curl -s -X POST http://127.0.0.1:8000/api/wishlist/add/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"item_id": 10}'
```

## Reviews and ratings

### Model constraints

Reviews are stored in `core.models.Review`:

- unique constraint: one review per `(user, item)`
- `rating` is 1..5
- `is_hidden` flag supports moderation/hiding

### Purchaser-only policy

Review creation/update is restricted to users who have purchased the item, as detected by:

- existence of an `Order` with `ordered=True` containing the item

This is enforced in the API (`core/api_reviews.py`) and in the product page template flow (`ItemDetailView.post`).

### Admin moderation

Admins can hide/unhide reviews via API endpoints (see below) and also via Django admin (models are registered in `core/admin.py`).

### API endpoints (`/api/reviews/**`)

Implemented in `core/api_reviews.py` and mounted in `core/urls.py`:

Public:

- `GET /api/reviews/items/<item_id>/` list visible reviews + stats

Authenticated user:

- `POST /api/reviews/items/<item_id>/me/` create/update the user’s review (purchaser-only)
- `DELETE /api/reviews/items/<item_id>/me/delete/` delete the user’s review

Admin moderation:

- `POST /api/reviews/<review_id>/hide/`
- `POST /api/reviews/<review_id>/unhide/`

## Coupons and discounts (v2)

## Overview

Coupons support both fixed and percentage discounts and include validation rules for:

- active flag
- start/end validity windows
- minimum order total
- global maximum redemptions
- per-user usage limits

The project preserves backward compatibility with an older fixed-amount field (`Coupon.amount`), but prefers new fields.

### Coupon fields

Implemented in `core.models.Coupon`:

- `code` (unique)
- `discount_type`: `fixed` or `percent`
- `percent_off` (required for percent coupons)
- `fixed_amount_off` (preferred for fixed coupons)
- legacy `amount` (still supported)
- `starts_at`, `ends_at`
- `min_order_total`
- `max_redemptions`, `max_uses_per_user`
- `redemption_count` (system maintained)

### Apply/remove flows

Template flows:

- Apply: `POST /add-coupon/` (uses `Order.apply_coupon()` with validation)
- Remove: `GET /remove-coupon/` (idempotent)

Where totals appear in UI:

- Order totals are displayed in the template order summary (`order_summary.html` includes `get_total()`).
- Discounts are reflected by `Order.get_total()` which subtracts the computed coupon discount.

### Redemption accounting (idempotent)

Successful coupon usage is recorded only after payment succeeds:

- `Order.record_coupon_redemption_if_needed()`

This creates `CouponRedemption` rows (unique per coupon+order) and increments `Coupon.redemption_count` under lock.

This means:
- applying a coupon to a cart does not “consume” a redemption
- only a paid order increments counters

## Admin item CRUD API (legacy)

In addition to the product-management endpoints, the project includes a legacy admin CRUD surface for items:

- `GET/POST /api/admin/items/`
- `GET/PUT/PATCH/DELETE /api/admin/items/<item_id>/`

These endpoints are admin-only and use a smaller serializer that covers legacy fields.
