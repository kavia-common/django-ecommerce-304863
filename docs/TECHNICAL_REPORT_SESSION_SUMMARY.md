# Technical Report: Session Summary and Current System State (Django E-commerce)

## 1) Project overview and scope

This repository (`django-ecommerce-304863/`) is a monolithic Django e-commerce application providing a classic server-rendered storefront (Django templates) and a JSON API surface for programmatic access. The storefront covers product browsing, cart, checkout, and payment pages, while the API layer provides JWT-authenticated endpoints for admin and user features such as product management, inventory operations, order status operations, wishlist management, review/rating workflows, and coupon behavior.

The session’s work modernized the project for Python 3.12 and Django 4.2 LTS, introduced and hardened the API authentication strategy (SimpleJWT) while retaining session authentication for template routes (django-allauth), added consistent role-based access control (RBAC) for admin surfaces, enhanced core commerce features (inventory controls, order lifecycle), and implemented Stripe PaymentIntents with webhook processing designed for safe idempotency.

Primary “source of truth” references for this summary include:

- System overview and operational reference: `docs/README.md`
- Deployment guidance: `docs/DEPLOYMENT_CHECKLIST.md`
- Auth/RBAC decision record: `docs/ADR-001-jwt-rbac.md`
- Django settings and security hardening: `djecommerce/settings/base.py`, `djecommerce/settings/production.py`, `djecommerce/settings/test.py`
- Core commerce and API logic: `core/models.py`, `core/views.py`, `core/api_views.py`, `core/api_admin_products.py`, `core/api_wishlist.py`, `core/api_reviews.py`, `core/stripe_webhooks.py`
- Tests and critical flow coverage: `core/test_critical_flows.py`, `core/tests.py`

## 2) Architecture and auth strategy (django-allauth + DRF SimpleJWT)

The system now explicitly supports two authentication modes, separated by route type and threat model:

### 2.1 Session authentication for template routes (django-allauth)

Template-rendered storefront routes continue to use Django sessions and django-allauth. Allauth is installed and configured in `djecommerce/settings/base.py` (`INSTALLED_APPS` includes `allauth`, `allauth.account`, `allauth.socialaccount`; and `AUTHENTICATION_BACKENDS` includes allauth’s backend). This preserves the existing browser flows and CSRF protections.

Relevant references:

- `djecommerce/settings/base.py` (installed apps, middleware, auth backends)
- `docs/ADR-001-jwt-rbac.md` (sessions for template routes)
- `docs/README.md` (boundary explanation)

### 2.2 JWT authentication for `/api/**` routes (DRF + SimpleJWT)

API endpoints use Django REST Framework with SimpleJWT bearer token authentication. The base settings configure:

- `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = ('rest_framework_simplejwt.authentication.JWTAuthentication',)`
- `REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'] = ('rest_framework.permissions.IsAuthenticated',)`

JWT signing uses a dedicated signing key:

- `JWT_SIGNING_KEY = config('JWT_SIGNING_KEY', default=SECRET_KEY)`
- `SIMPLE_JWT['SIGNING_KEY'] = JWT_SIGNING_KEY`

This means production should set `JWT_SIGNING_KEY` to decouple JWT rotation from Django’s `SECRET_KEY`.

Relevant references:

- `djecommerce/settings/base.py` (DRF + SIMPLE_JWT configuration)
- `docs/ADR-001-jwt-rbac.md` (decision and consequences)
- `docs/README.md` (API auth usage and curl examples)

### 2.3 ADR reference

The architectural decision is captured in:

- `docs/ADR-001-jwt-rbac.md`

That ADR documents: (a) JWT for APIs, (b) sessions for templates, and (c) RBAC definition and enforcement paths.

## 3) Feature implementation details

This section describes the implemented features requested, focusing on current code behavior and where it lives.

### 3.1 RBAC (admin role model and enforcement)

Admin authorization uses a simple “admin role” definition:

A user is considered admin if they are authenticated and any of these is true:

- `user.is_superuser`
- `user.is_staff`
- user belongs to Django `Group` named `Admin`

RBAC logic is centralized in:

- `core/rbac.py` (helpers like `is_admin_user` / `request_is_admin`)
- `core/api_permissions.py` (`IsAdminRole` DRF permission)

RBAC bootstrapping is provided by a management command:

- `core/management/commands/setup_rbac.py`

That command ensures the `Admin` group exists and assigns model permissions for `Item` and `Order` (useful for admin UI and consistent group semantics).

Admin-only enforcement occurs in two domains:

1. API endpoints: DRF permission `IsAdminRole` is added to admin endpoints (e.g., `core/api_views.py`, `core/api_admin_products.py`).
2. Template management views: `user_passes_test(request_is_admin)` in `core/views.py` for `/manage/**` operations pages.

Relevant references:

- `core/rbac.py`
- `core/api_permissions.py`
- `core/management/commands/setup_rbac.py`
- `core/views.py` (template admin views)
- `core/api_views.py`, `core/api_admin_products.py` (admin APIs)

### 3.2 Product management (categories + item CRUD)

A more “production-ready” product model structure was introduced while retaining backwards compatibility with legacy templates:

- `core/models.py` defines `Category` and `Item`.
- `Item` keeps the legacy `category` choice field but adds `category_obj` (FK to `Category`) and operational fields like `sku`, `active`, and inventory fields.

Admin APIs for product/category management are implemented in:

- `core/api_admin_products.py`

Key endpoints (as documented in `docs/README.md`) include category CRUD and item CRUD under `/api/admin/products/**`, plus item deactivation and inventory adjustment routes.

Notable behaviors:

- Storefront hides inactive products via `ActiveItemManager` (`Item.objects` returns only active items), while admin queries use `Item.all_objects`.
- `sku` is unique (DB constraint).

Relevant references:

- `core/models.py` (`Category`, `Item`, managers)
- `core/api_admin_products.py` (admin APIs)
- `docs/README.md` (endpoint reference)

### 3.3 Inventory management (oversell prevention and atomic decrement)

Inventory tracking is implemented on `Item`:

- `track_inventory` (boolean)
- `stock_quantity` (non-negative integer)

Oversell prevention is enforced at multiple layers:

1. Adding to cart blocks quantities beyond stock when `track_inventory` is enabled:
   - `core/views.py` (`add_to_cart` checks `stock_quantity` and caps quantity changes)
2. Checkout and payment perform defensive validation before proceeding:
   - `CheckoutView.get/post` validates each order item via `Item.ensure_can_fulfill`
   - `PaymentView.get/post` repeats that validation before charging/finalizing
3. Finalization decrements stock atomically and only after confirmed payment success:
   - `Item.atomic_decrement_stock_for_order(order)` in `core/models.py` uses `select_for_update()` and `F()` updates
   - `_finalize_order_after_successful_payment` in `core/views.py` wraps decrement + order finalization in `transaction.atomic()`

Admin inventory adjustments are also atomic and prevent negative stock:

- Legacy admin adjust: `POST /api/admin/inventory/adjust/` in `core/api_views.py`
- Preferred product inventory endpoint: `POST /api/admin/products/items/<id>/inventory/` in `core/api_admin_products.py`

Relevant references:

- `core/models.py` (`Item.ensure_can_fulfill`, `Item.atomic_decrement_stock_for_order`)
- `core/views.py` (`CheckoutView`, `PaymentView`, `add_to_cart`, `_finalize_order_after_successful_payment`)
- `core/api_views.py` and `core/api_admin_products.py` (inventory admin APIs)

### 3.4 Order lifecycle enum (placed → shipped → delivered)

An explicit order lifecycle is implemented on `Order`:

- `Order.status` uses `Order.OrderStatus` enum (`placed`, `shipped`, `delivered`)
- Milestone timestamps: `placed_at`, `shipped_at`, `delivered_at`
- Legacy boolean flags (`being_delivered`, `received`) remain for backward compatibility and are synced through the transition logic.

The lifecycle transition policy is intentionally simple and forward-only:

- `placed → shipped → delivered`
- Same-status transitions are treated as no-ops
- “Unpaid carts” (orders with `ordered=False`) cannot transition to `shipped` or `delivered` (defense-in-depth)

Core methods:

- `Order.can_transition_to(new_status)` and `Order.transition_to(new_status, ...)` in `core/models.py`
- Admin transition endpoints in:
  - `core/api_views.py` (`api_admin_order_transition`)
  - `core/views.py` (`admin_order_transition` template view)

Relevant references:

- `core/models.py` (`Order.OrderStatus`, transition logic)
- `core/api_views.py` (admin order transition API)
- `core/views.py` (admin template transition flow)
- `docs/README.md` (order lifecycle section)

### 3.5 Stripe payments: PaymentIntents + webhook processing (with idempotency)

The system supports two payment paths:

1. Preferred: PaymentIntents flow (Stripe.js client confirms PaymentIntent, then server verifies status)
2. Fallback: legacy token → Charge flow (preserved for template compatibility)

#### 3.5.1 PaymentIntents creation and synchronous finalize

In `core/views.py`:

- `PaymentView.get` attempts to create a PaymentIntent:
  - `amount = int(order.get_total() * 100)`
  - `automatic_payment_methods={"enabled": True}`
  - metadata includes `order_id` and `user_id`
  - uses Stripe idempotency key: `idempotency_key=f"order_{order.id}_pi_create"` to prevent duplicate PIs on refresh

- `PaymentView.post` finalizes only if:
  - a `payment_intent_id` is posted, and
  - `stripe.PaymentIntent.retrieve(payment_intent_id)["status"] == "succeeded"`

Then it creates a `Payment` record and calls `_finalize_order_after_successful_payment`, which:
- decrements inventory atomically
- marks order items ordered
- marks `order.ordered = True`
- sets ref_code
- transitions order to `placed` (defensively)
- records coupon redemption (defensively and non-blocking)

Relevant references:

- `core/views.py` (`PaymentView`, `_finalize_order_after_successful_payment`)

#### 3.5.2 Webhook endpoint, verification, and idempotency

The Stripe webhook endpoint is implemented in:

- `core/stripe_webhooks.py` (`stripe_webhook`)

Properties:

- CSRF exempt (`@csrf_exempt`), as Stripe is not a browser client.
- Signature verification:
  - If `settings.STRIPE_WEBHOOK_SECRET` is set (non-empty), the webhook verifies `Stripe-Signature` using `stripe.Webhook.construct_event`.
  - If the secret is empty, it falls back to unsigned parsing (development convenience; not recommended for production).

Idempotency:

- The webhook stores Stripe event id in `Payment.stripe_event_id`, which is defined as `unique=True` in `core/models.py`.
- The handler checks for an existing `Payment` with that `stripe_event_id` and returns `200` immediately for duplicate deliveries.
- On `payment_intent.succeeded`, it creates a `Payment` row with `stripe_event_id` and finalizes the order (stock decrement + order completion) inside a DB transaction.

Relevant references:

- `core/stripe_webhooks.py`
- `core/models.py` (`Payment.stripe_event_id` unique)
- `docs/README.md` and `docs/DEPLOYMENT_CHECKLIST.md` (operational behavior)

### 3.6 Wishlist

Wishlist functionality is implemented as an explicit through model:

- `core/models.py`: `WishlistEntry` with a uniqueness constraint on `(user, item)`.

API endpoints are implemented in:

- `core/api_wishlist.py`:
  - `GET /api/wishlist/`
  - `POST /api/wishlist/add/` (duplicate add is safe; returns 200 “Already in wishlist”)
  - `POST /api/wishlist/remove/` (idempotent)

Relevant references:

- `core/models.py` (`WishlistEntry`)
- `core/api_wishlist.py`
- `docs/README.md` (endpoint examples)

### 3.7 Reviews and ratings

Reviews are implemented in:

- `core/models.py`: `Review` with uniqueness constraint `(user, item)`, plus `is_hidden` moderation flag.

Policy:

- Only purchasers can review (as best-effort detectability):
  - `user_has_purchased_item(user, item)` checks for an `Order` with `ordered=True` containing an `OrderItem` referencing that item.
  - This gating is enforced in API endpoints and in the product detail template POST path.

API endpoints are implemented in:

- `core/api_reviews.py`:
  - Public list: `GET /api/reviews/items/<item_id>/` returns visible reviews and simple stats
  - User upsert: `POST /api/reviews/items/<item_id>/me/` (authenticated + purchaser-only)
  - User delete: `DELETE /api/reviews/items/<item_id>/me/delete/` (as described in docs; verify actual URL mapping in `core/urls.py`)
  - Admin moderation: `POST /api/reviews/<review_id>/hide/` and `/unhide/` (admin-only)

Template integration:

- `core/views.py` (`ItemDetailView.get_context_data` for displaying visible reviews and showing a review form, and `ItemDetailView.post` for save/delete)

Relevant references:

- `core/models.py` (`Review`, `user_has_purchased_item`)
- `core/api_reviews.py`
- `core/views.py` (`ItemDetailView`)
- `docs/README.md`

### 3.8 Coupons/discounts v2

Coupons were expanded into a more robust model while retaining a legacy fixed-amount field:

- `core/models.py`: `Coupon` supports:
  - `discount_type`: fixed or percent
  - `percent_off`, `fixed_amount_off`, plus legacy `amount`
  - active flag and validity windows (`starts_at`, `ends_at`)
  - minimum order total
  - global max redemptions and per-user usage limits
  - `redemption_count` counter
- `CouponRedemption` records successful redemptions and enforces idempotency per order via unique constraint `(coupon, order)`.

Operational accounting:

- Applying a coupon does not consume redemption; it is recorded only after successful payment:
  - `_finalize_order_after_successful_payment` calls `order.record_coupon_redemption_if_needed()` (defensively).

Template flows:

- `core/views.py`: `AddCouponView` applies coupons to the active cart after calling `order.apply_coupon(...)`
- `core/views.py`: `remove_coupon` removes coupon idempotently

Relevant references:

- `core/models.py` (`Coupon`, `CouponRedemption`, and apply/validate/record methods)
- `core/views.py` (`AddCouponView`, `remove_coupon`)
- `core/tests.py` and `core/test_critical_flows.py` (coupon tests)

## 4) Dependency modernization for Python 3.12 (Django 4.2 LTS) and `sitecustomize.py` rationale

### 4.1 Requirements and version pins

The repository is pinned for Python 3.12 compatibility in:

- `requirements.txt`

Notable pins include:

- Django `4.2.27` (LTS)
- DRF `3.15.2`
- SimpleJWT `5.4.0`
- django-allauth `0.63.6`
- django-csp `3.8`
- stripe `10.12.0`

These choices align with modern Django/Python versions and reduce reliance on deprecated compatibility shims (notably `django.utils.six` patterns).

Relevant reference:

- `requirements.txt`

### 4.2 `sitecustomize.py`

A `sitecustomize.py` exists at the project root:

- `sitecustomize.py`

Its content documents that the project historically needed shims for legacy `django.utils.six` / `six` meta path importers that are incompatible with Python 3.12. The repository has been upgraded so those shims should no longer be required, but the file remains as a safe no-op placeholder to avoid surprises in environments that auto-import `sitecustomize`.

Relevant reference:

- `sitecustomize.py`

## 5) Security hardening

Security hardening is primarily configured in:

- `djecommerce/settings/base.py` (env-driven defaults, CSP, cookies, throttling, logging)
- `djecommerce/settings/production.py` (secure defaults suitable for prod)

### 5.1 Content Security Policy (CSP) via `django-csp`

`django-csp` is installed (`csp` app) and CSP middleware is enabled early:

- `csp.middleware.CSPMiddleware` is inserted after `django.middleware.security.SecurityMiddleware`.

Baseline CSP directives allow Stripe usage for the payment page:

- `CSP_DEFAULT_SRC = ("'self'",)`
- `CSP_SCRIPT_SRC` includes `'self'`, `'unsafe-inline'`, and `https://js.stripe.com`
- `CSP_FRAME_SRC` includes `https://js.stripe.com`
- `CSP_CONNECT_SRC` includes `'self'` and `https://api.stripe.com`
- `CSP_IMG_SRC` includes `'self'` and `data:`
- `CSP_STYLE_SRC` includes `'self'` and `'unsafe-inline'`

CSP report-only mode is environment driven:

- `CSP_REPORT_ONLY = config('DJANGO_CSP_REPORT_ONLY', cast=bool, default=DEBUG)` in base
- Production defaults to enforcing: `CSP_REPORT_ONLY = ... default=False` in `production.py`

Allowlist extension is supported via comma-separated env vars:

- `DJANGO_CSP_ADDITIONAL_SCRIPT_SRC`
- `DJANGO_CSP_ADDITIONAL_STYLE_SRC`
- `DJANGO_CSP_ADDITIONAL_CONNECT_SRC`
- `DJANGO_CSP_ADDITIONAL_IMG_SRC`
- `DJANGO_CSP_ADDITIONAL_FRAME_SRC`

Relevant references:

- `djecommerce/settings/base.py`
- `djecommerce/settings/production.py`
- `docs/README.md` (CSP overview and operational guidance)

### 5.2 `SECURE_*` flags and cookie/session configuration

The system uses environment-controlled security flags with production-ready defaults:

- `SECURE_SSL_REDIRECT` controlled by `DJANGO_SECURE_SSL_REDIRECT` (default False in base, True default in production module)
- HSTS:
  - `SECURE_HSTS_SECONDS` configurable via `DJANGO_SECURE_HSTS_SECONDS` (0 default in base, 31536000 default in production)
  - `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
  - `SECURE_HSTS_PRELOAD = True`
- Secure cookies:
  - `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` default to follow `SECURE_SSL_REDIRECT` in base
  - production overrides default to True
- SameSite defaults:
  - `SESSION_COOKIE_SAMESITE = 'Lax'`
  - `CSRF_COOKIE_SAMESITE = 'Lax'`
- HttpOnly:
  - `SESSION_COOKIE_HTTPONLY = True`
  - `CSRF_COOKIE_HTTPONLY = False` (explicitly documented as a Django constraint)
- Reverse proxy/TLS terminator support:
  - `DJANGO_SECURE_PROXY_SSL_HEADER` parsed into `SECURE_PROXY_SSL_HEADER` and validated.

Relevant references:

- `djecommerce/settings/base.py`
- `djecommerce/settings/production.py`
- `docs/DEPLOYMENT_CHECKLIST.md` (deployment-specific recommendations)

### 5.3 DRF throttling

DRF throttling is enabled by default as a baseline protection against abuse:

- throttle classes:
  - `AnonRateThrottle`
  - `UserRateThrottle`
- rates:
  - `DRF_THROTTLE_ANON` default `60/min`
  - `DRF_THROTTLE_USER` default `600/min`

Relevant reference:

- `djecommerce/settings/base.py`

### 5.4 Logging hygiene

`djecommerce/settings/base.py` defines console logging and explicitly configures security loggers:

- `django.security`
- `django.security.SuspiciousOperation`

Log levels can be controlled via:

- `DJANGO_LOG_LEVEL` (default INFO)
- `DJANGO_SECURITY_LOG_LEVEL` (default WARNING)

Relevant reference:

- `djecommerce/settings/base.py`

## 6) Testing summary

### 6.1 Test modules and covered critical flows

Two main test modules provide coverage:

- `core/test_critical_flows.py` (broad “critical flow” tests)
- `core/tests.py` (targeted wishlist/coupon tests)

The critical flows test suite includes:

- JWT obtain/verify/refresh and protected `/api/auth/me/` behavior
- RBAC protections for admin endpoints and template management routes
- Inventory checks at cart and payment time, plus atomic decrement on finalize
- Order lifecycle transitions and rejection of invalid transitions / unpaid cart transitions
- Stripe PaymentIntent finalization behavior (only succeeded PaymentIntents finalize)
- Stripe webhook processing and idempotency (duplicate event id does not double-decrement stock)
- Wishlist: list/add/remove and no duplicates
- Reviews: purchaser-only policy, upsert semantics, rating validation, and admin hide/unhide
- Coupons v2: percent/fixed totals, validity window/min order enforcement, global/per-user limits, and template apply/remove flows

Relevant references:

- `core/test_critical_flows.py`
- `core/tests.py`

### 6.2 Test settings module (CI-friendly)

A dedicated test settings module exists:

- `djecommerce/settings/test.py`

It supplies dummy secrets so test runs do not require production secrets:

- `SECRET_KEY = "dummy-secret-key-for-tests-only"`
- `JWT_SIGNING_KEY = "dummy-jwt-signing-key-for-tests-only"`
- Stripe dummy keys (`STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`) and aliases for test/live variable variants

It also:

- sets `CSP_REPORT_ONLY = True` to avoid blocking during tests
- disables secure redirects/cookies for HTTP test environment
- uses a fast password hasher for speed

Relevant references:

- `djecommerce/settings/test.py`
- `docs/README.md` and `docs/DEPLOYMENT_CHECKLIST.md` (test invocation guidance)

### 6.3 How to run tests

The recommended command is:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.test python manage.py test
```

Note that `manage.py` defaults to development settings (`djecommerce.settings.development`) unless overridden:

- `manage.py` sets `os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djecommerce.settings.development')`

Relevant references:

- `djecommerce/settings/test.py`
- `manage.py`

### 6.4 Current status caveat

This report documents test presence and intent based on the repository contents. It does not assert that the entire suite was executed successfully in the current environment during this documentation run. The recommended next action remains to run the full test suite in CI mode and confirm Stripe tests/mocks remain stable.

## 7) Documentation artifacts created (and where they are)

The repository already contains the following documentation artifacts (which this report references and builds upon):

- `docs/README.md` (primary operational and developer reference)
- `docs/DEPLOYMENT_CHECKLIST.md` (production deployment checklist)
- `docs/ADR-001-jwt-rbac.md` (architectural decision record for JWT + RBAC)

Additional related docs present:

- `docs/OPERATIONS_RUNBOOK.md`
- `docs/FEATURES_AND_APIS.md`
- `docs/AUTH_AND_RBAC.md`
- `docs/SETUP.md`

This session-summary report is added as:

- `docs/TECHNICAL_REPORT_SESSION_SUMMARY.md`

## 8) Environment variables required (authoritative vs requested names)

### 8.1 Authoritative env vars used by this repo (recommended to set)

Core:

- `SECRET_KEY` (required) — read in `djecommerce/settings/base.py`
- `DEBUG` (required when using production settings) — read in `djecommerce/settings/production.py`

JWT:

- `JWT_SIGNING_KEY` (recommended in production) — read in `djecommerce/settings/base.py` (falls back to `SECRET_KEY` if unset)

Stripe (production module expects live keys):

- `STRIPE_LIVE_PUBLIC_KEY` — read in `djecommerce/settings/production.py`
- `STRIPE_LIVE_SECRET_KEY` — read in `djecommerce/settings/production.py`
- `STRIPE_WEBHOOK_SECRET` (strongly recommended for production) — read in `djecommerce/settings/production.py` and used by `core/stripe_webhooks.py`

Security and operational toggles (optional but strongly recommended in production):

- `DJANGO_ALLOWED_HOSTS` (comma-separated)
- `DJANGO_CSRF_TRUSTED_ORIGINS` (comma-separated)
- `DJANGO_SECURE_SSL_REDIRECT` (bool)
- `DJANGO_SECURE_HSTS_SECONDS` (int)
- `DJANGO_SECURE_PROXY_SSL_HEADER` (string: `HTTP_X_FORWARDED_PROTO,https`)
- `DJANGO_SESSION_COOKIE_SECURE` (bool)
- `DJANGO_CSRF_COOKIE_SECURE` (bool)
- `DJANGO_CSP_REPORT_ONLY` (bool)
- `DJANGO_CSP_ADDITIONAL_*` allowlist variables (comma-separated)
- `DRF_THROTTLE_ANON` and `DRF_THROTTLE_USER`
- `DJANGO_LOG_LEVEL` and `DJANGO_SECURITY_LOG_LEVEL`

Relevant references:

- `djecommerce/settings/base.py`
- `djecommerce/settings/production.py`
- `docs/README.md`
- `docs/DEPLOYMENT_CHECKLIST.md`

### 8.2 Requested variable names vs actual code expectations

The request mentioned variable names including `JWT_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `SECRET_KEY`.

In the current repository:

- JWT uses `JWT_SIGNING_KEY` (not `JWT_SECRET_KEY`) in `djecommerce/settings/base.py`.
- Stripe keys are environment-specific in settings modules:
  - production reads `STRIPE_LIVE_PUBLIC_KEY` and `STRIPE_LIVE_SECRET_KEY`
  - test settings defines dummy `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` and aliases them to `STRIPE_TEST_*` and `STRIPE_LIVE_*` for compatibility inside tests
- `STRIPE_WEBHOOK_SECRET` is the webhook signing secret name used by `core/stripe_webhooks.py` (via `settings.STRIPE_WEBHOOK_SECRET`), and `production.py` reads it from env.

If an external platform expects a single pair like `STRIPE_PUBLISHABLE_KEY` and `STRIPE_SECRET_KEY`, you should either map them into `STRIPE_LIVE_PUBLIC_KEY`/`STRIPE_LIVE_SECRET_KEY` at deploy time or adapt settings to accept those aliases. The current authoritative code paths are the ones listed above.

## 9) Operational runbooks (Stripe setup, order lifecycle management, inventory ops)

This section summarizes the operator flows and links to the more detailed documents.

### 9.1 Stripe setup and webhook operations

Operator steps:

1. Ensure Stripe keys are configured for the chosen settings module:
   - Production: set `STRIPE_LIVE_PUBLIC_KEY` and `STRIPE_LIVE_SECRET_KEY`
2. Configure webhook signing secret:
   - Set `STRIPE_WEBHOOK_SECRET` (non-empty) so `core/stripe_webhooks.py` performs signature verification.
3. Create Stripe dashboard webhook endpoint:
   - URL: `https://<your-domain>/stripe/webhook/`
   - Send at least: `payment_intent.succeeded` (and optionally `payment_intent.payment_failed`)
4. Ensure your reverse proxy forwards the `Stripe-Signature` header.

Idempotency expectation:

- Duplicate deliveries should be safe because `Payment.stripe_event_id` is unique and checked.

Relevant references:

- `core/stripe_webhooks.py`
- `core/models.py` (`Payment.stripe_event_id`)
- `docs/DEPLOYMENT_CHECKLIST.md` (Stripe section)
- `docs/README.md` and `docs/OPERATIONS_RUNBOOK.md`

### 9.2 Order lifecycle management (admin operations)

Admin management is possible via:

- Template routes (session auth + admin role):
  - `/manage/orders/` and `/manage/orders/<order_id>/transition/` in `core/views.py`
- API routes (JWT + admin role):
  - `/api/admin/orders/` and `/api/admin/orders/<order_id>/transition/` in `core/api_views.py`

Operational rules:

- Only paid orders (`ordered=True`) can be shipped/delivered.
- Status transitions must follow the forward-only lifecycle.

Relevant references:

- `core/models.py` (transition rules)
- `core/api_views.py` (transition API)
- `core/views.py` (template admin transition)
- `docs/README.md` (order lifecycle section)

### 9.3 Inventory operations

Inventory is managed through:

- Admin API inventory adjustment endpoints:
  - `/api/admin/inventory/adjust/` (legacy)
  - `/api/admin/products/items/<id>/inventory/` (preferred)
- Storefront and payment enforce stock validation and only decrement on successful payment confirmation.

Operational guidance:

- Prefer adjusting stock via the admin inventory endpoints to preserve constraints and atomicity.
- If an item is oversold or needs to be removed from sale quickly, set `active=false` via admin item update or the deactivate endpoint.

Relevant references:

- `core/models.py` (`Item.atomic_decrement_stock_for_order`)
- `core/api_views.py` and `core/api_admin_products.py` (inventory endpoints)
- `core/views.py` (cart/checkout/payment validations)
- `docs/OPERATIONS_RUNBOOK.md`

## 10) Known gaps, risks, and recommended next actions

### 10.1 Known gaps / risks

1. Webhook fallback mode is dev-friendly but risky in production. If `STRIPE_WEBHOOK_SECRET` is empty, `core/stripe_webhooks.py` accepts unsigned events. This is not appropriate for any internet-facing deployment. The risk is unauthorized order finalization if a malicious actor can reach the endpoint and craft payloads.

2. Stripe PaymentIntents client integration details depend on templates. The code passes `stripe_payment_intent_client_secret` to `templates/payment.html` and expects client-side JS to confirm the payment and POST `payment_intent_id`. Any CSP tightening (removing `'unsafe-inline'`) could break payment page behavior unless nonces/hashes are implemented.

3. Test suite execution status is not asserted by this report. The repository contains substantial tests, but the correct next operational step is to run the full suite in the intended environment and ensure it is passing end-to-end.

4. Env var naming mismatch can cause deployment errors if operators use different conventions (e.g., `JWT_SECRET_KEY` vs `JWT_SIGNING_KEY`, or a single `STRIPE_SECRET_KEY` vs `STRIPE_LIVE_SECRET_KEY`). This risk is operational rather than functional, but it is a common source of misconfiguration.

### 10.2 Recommended next actions

1. Run the full test suite with test settings:
   - `DJANGO_SETTINGS_MODULE=djecommerce.settings.test python manage.py test`
   - Confirm no hidden reliance on development settings or live Stripe calls.

2. Enforce webhook signature verification in production:
   - Ensure `STRIPE_WEBHOOK_SECRET` is always set in the production environment.
   - Confirm reverse proxy forwards `Stripe-Signature` intact.

3. Finalize CSP for production origins and third-party additions:
   - Set `DJANGO_CSP_REPORT_ONLY=false` and review browser reports.
   - Use `DJANGO_CSP_ADDITIONAL_*` env vars to add required domains rather than weakening defaults.

4. Confirm operational environment variable mapping:
   - Decide whether to standardize on repository names (`JWT_SIGNING_KEY`, `STRIPE_LIVE_*`) or add alias reads in settings for platform conventions.

5. Perform a staging end-to-end payment test:
   - Create a paid order via PaymentIntent flow.
   - Confirm inventory decrements once.
   - Confirm duplicate webhook deliveries do not cause double-decrement.

6. Consider adding a dedicated health endpoint if needed for infrastructure:
   - Currently, `docs/DEPLOYMENT_CHECKLIST.md` notes there is no `/health/` endpoint; operators can use `GET /` as a basic liveness probe.

Relevant references for these actions:

- `docs/DEPLOYMENT_CHECKLIST.md`
- `docs/README.md`
- `core/stripe_webhooks.py`
- `djecommerce/settings/base.py`, `djecommerce/settings/production.py`, `djecommerce/settings/test.py`
