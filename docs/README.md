# Django E-commerce: Setup, Auth, APIs, and Operations

## Overview

This repository contains a Django-based e-commerce application with a classic server-rendered storefront (Django templates) and a JSON API layer for programmatic access. The API layer uses Django REST Framework (DRF) and JWT authentication (SimpleJWT). The browser/template flows use Django sessions via `django-allauth`.

This document is the primary “production-ready” operational and developer reference. It is grounded in the implementation in:

- `djecommerce/settings/*` (settings and environment variables)
- `djecommerce/urls.py` and `core/urls.py` (URL routing and endpoint locations)
- `core/rbac.py` and `core/api_permissions.py` (RBAC and admin authorization boundary)
- `core/models.py` (inventory + order lifecycle + coupons)
- `core/views.py` and `core/stripe_webhooks.py` (Stripe payment flows and webhook processing)
- `core/test_critical_flows.py` (test coverage and recommended test commands)

For the architectural decision behind JWT + RBAC, see:

- `docs/ADR-001-jwt-rbac.md`

## Project setup guide (Python 3.12)

### Prerequisites

- Python 3.12
- `pip`
- A local database (SQLite for development, PostgreSQL for production)
- Stripe account (optional for non-payment development, required for payment flows)

The project is pinned to modern dependencies compatible with Python 3.12 (notably Django 4.2 LTS) in:

- `requirements.txt`

### Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment variables

Create a `.env` file in the project root (same directory as `manage.py`). Settings use `python-decouple` (via `decouple.config`) to read environment variables.

The required variables and their meanings are documented in the “Environment variables” section below.

### Run migrations

```bash
python manage.py migrate
```

### Bootstrap RBAC (create Admin group and permissions)

```bash
python manage.py setup_rbac
```

This command is implemented in `core/management/commands/setup_rbac.py` and ensures the `Admin` group exists and has model-level permissions for `Item` and `Order`. RBAC enforcement is also applied at the view/permission layer (see “RBAC usage”).

### Create a superuser (admin access)

If you need Django admin UI access (`/admin/`) and a privileged operator account:

```bash
python manage.py createsuperuser
```

A superuser is always treated as “admin role” for protected admin APIs and management routes.

### Start the development server

```bash
python manage.py runserver
```

Default: `http://127.0.0.1:8000/`.

### Basic smoke checks

1. Storefront loads:

- `GET /`

2. Obtain a JWT token pair:

- `POST /api/auth/token/`

3. Call a JWT-protected endpoint:

- `GET /api/auth/me/`

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<user>","password":"<pass>"}'
```

Then:

```bash
curl -s http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

## Settings modules

Settings are split across:

- `djecommerce/settings/base.py`: shared settings, including DRF + SimpleJWT configuration.
- `djecommerce/settings/development.py`: local dev defaults (SQLite, debug toolbar, Stripe test keys).
- `djecommerce/settings/production.py`: production defaults (PostgreSQL, password validators, Stripe live keys).
- `djecommerce/settings/test.py`: test-only overrides with dummy secrets suitable for CI.

## Environment variables (configuration reference)

This project reads environment variables using `python-decouple` (`decouple.config`). The authoritative reads are in:

- `djecommerce/settings/base.py`
- `djecommerce/settings/development.py`
- `djecommerce/settings/production.py`
- `djecommerce/settings/test.py` (dummy values for CI)

### Core Django secrets

#### `SECRET_KEY` (required)

Used for Django cryptographic signing.

Source: `djecommerce/settings/base.py` (`SECRET_KEY = config('SECRET_KEY')`).

Operational note: this must be unique per environment and never committed.

### JWT / API authentication

#### `JWT_SIGNING_KEY` (optional, strongly recommended in production)

Signing key for JWTs issued by SimpleJWT.

Source: `djecommerce/settings/base.py`:

- `JWT_SIGNING_KEY = config('JWT_SIGNING_KEY', default=SECRET_KEY)`
- `SIMPLE_JWT['SIGNING_KEY'] = JWT_SIGNING_KEY`

Operational note: in production, set a dedicated `JWT_SIGNING_KEY` separate from `SECRET_KEY` so you can rotate JWTs independently of Django’s session/cookie signing.

### Stripe payments

Stripe keys differ by environment.

#### Development (test mode) keys

Configured in `djecommerce/settings/development.py`.

##### `STRIPE_TEST_PUBLIC_KEY` (required for dev payments)

Mapped to `settings.STRIPE_PUBLIC_KEY` in development settings and passed into the payment template.

##### `STRIPE_TEST_SECRET_KEY` (required for dev payments)

Mapped to `settings.STRIPE_SECRET_KEY` in development settings. Used by the Stripe SDK (`stripe.api_key = settings.STRIPE_SECRET_KEY` in `core/views.py`).

##### `STRIPE_TEST_WEBHOOK_SECRET` (optional)

Mapped to `settings.STRIPE_WEBHOOK_SECRET` in development settings:

- If set (non-empty), `core/stripe_webhooks.py` verifies Stripe webhook signatures.
- If unset/empty, webhook parsing falls back to unsigned event parsing for local convenience.

Production guidance: do not run webhook processing without signature verification in any real deployment.

#### Production (live mode) keys

Configured in `djecommerce/settings/production.py`.

##### `STRIPE_LIVE_PUBLIC_KEY` (required for production payments)

Mapped to `settings.STRIPE_PUBLIC_KEY`.

##### `STRIPE_LIVE_SECRET_KEY` (required for production payments)

Mapped to `settings.STRIPE_SECRET_KEY`.

##### `STRIPE_WEBHOOK_SECRET` (recommended for production webhook verification)

The webhook handler reads `settings.STRIPE_WEBHOOK_SECRET` (`core/stripe_webhooks.py`). The production settings module does not currently define it explicitly, so you must ensure it is available as `STRIPE_WEBHOOK_SECRET` in the runtime settings environment. In practice, you should either:

1. Extend `production.py` to read it, or
2. Provide it via an environment-driven mechanism in your deployment that ensures `settings.STRIPE_WEBHOOK_SECRET` is set.

### Production database settings

When running with `djecommerce/settings/production.py`, PostgreSQL settings require:

- `DEBUG` (required by `production.py`, cast to bool)
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`

Source: `djecommerce/settings/production.py`.

### Notes about “requested” variable names

Some environments expect variables named `JWT_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET`. In this repository’s current implementation:

- The JWT env var is `JWT_SIGNING_KEY` (not `JWT_SECRET_KEY`).
- Stripe keys are split into test/live names in development/production settings:
  - `STRIPE_TEST_PUBLIC_KEY` / `STRIPE_TEST_SECRET_KEY` / `STRIPE_TEST_WEBHOOK_SECRET`
  - `STRIPE_LIVE_PUBLIC_KEY` / `STRIPE_LIVE_SECRET_KEY`
- `djecommerce/settings/test.py` also defines generic dummy values:
  - `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET`
  - and aliases them into the `*_TEST_*` / `*_LIVE_*` names for defensive compatibility.

If you are integrating a `.env.example` file externally, align it to the names above (the code is authoritative).

## Auth model overview: sessions vs JWT (boundaries and security notes)

This project supports two authentication modes simultaneously. The intended boundary is strict:

### Browser / template flows: Django sessions via allauth

Template-rendered routes (for example `/`, `/checkout/`, `/payment/stripe/`, `/my/orders/`, `/wishlist/`) use standard Django authentication with sessions and `django-allauth`.

Allauth routes are mounted at:

- `/accounts/` (see `djecommerce/urls.py`)

Security characteristics:

- CSRF protection is enabled via `django.middleware.csrf.CsrfViewMiddleware` (see `MIDDLEWARE` in `djecommerce/settings/base.py`).
- State-changing POSTs from templates must include CSRF tokens (`{% csrf_token %}`).

### API flows: DRF + SimpleJWT (Bearer tokens)

API endpoints use DRF and SimpleJWT, with defaults in `djecommerce/settings/base.py`:

- Authentication: `rest_framework_simplejwt.authentication.JWTAuthentication`
- Default permission: `rest_framework.permissions.IsAuthenticated`

Security characteristics:

- API calls are intended to use `Authorization: Bearer <access_token>`.
- Because APIs are not cookie-authenticated by default, CSRF is not the primary protection mechanism for API requests.
- If you introduce cross-origin API usage from browsers, you must explicitly configure CORS. This repository does not include any CORS middleware configuration by default.

### Stripe webhook: CSRF exempt by design

The Stripe webhook endpoint is explicitly CSRF exempt:

- `@csrf_exempt` in `core/stripe_webhooks.py`

This is required because Stripe is not a browser client. Production safety relies on verifying the Stripe signature header using `STRIPE_WEBHOOK_SECRET`.

## RBAC usage (Admin group, setup command, role assignment, protected routes)

### How “admin role” is defined

Admin role is defined centrally in `core/rbac.py` and used consistently for:

- DRF permissions (`core/api_permissions.IsAdminRole`)
- Template admin routes under `/manage/**` (via `user_passes_test` and `core.rbac.request_is_admin`)

A user is considered admin if they are authenticated and any of the following is true:

- `is_superuser` is true
- `is_staff` is true
- Member of the Django group named `Admin`

Source: `core/rbac.py` (`is_admin_user`) and `core/api_permissions.py`.

### Bootstrapping RBAC

Run:

```bash
python manage.py setup_rbac
```

This ensures the `Admin` group exists and grants it model-level permissions for:

- `Item`
- `Order`

Source: `core/management/commands/setup_rbac.py`.

### Assigning roles

You can grant “admin role” in several ways:

1. Create a superuser:

```bash
python manage.py createsuperuser
```

2. Mark a user as staff (via Django admin UI, or programmatically).

3. Add a user to the `Admin` group.

Example via shell:

```python
# python manage.py shell
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()
u = User.objects.get(username="alice")
admin_group = Group.objects.get(name="Admin")
u.groups.add(admin_group)
```

### Protected routes summary

#### Admin-only API routes

Admin-only API endpoints require both:

- JWT authentication (Bearer token), and
- `IsAdminRole` (admin role)

Key admin-only API surfaces:

- `/api/admin/items/` and `/api/admin/items/<item_id>/` (legacy admin item CRUD; `djecommerce/urls.py` or `core/urls.py`)
- `/api/admin/inventory/adjust/` (legacy inventory adjust)
- `/api/admin/orders/` and `/api/admin/orders/<order_id>/` (admin order management)
- `/api/admin/orders/<order_id>/transition/` (admin transitions)
- `/api/admin/products/**` (preferred “product management” endpoints)

#### Admin-only template (session) routes

Admin-only management pages use session authentication and `user_passes_test`:

- `/manage/orders/`
- `/manage/orders/<order_id>/transition/`

Source: `core/urls.py` and `core/views.py`.

## API quick reference (endpoints + sample curl)

### JWT authentication endpoints

Mounted in `djecommerce/urls.py`:

- `POST /api/auth/token/` (obtain access + refresh)
- `POST /api/auth/token/refresh/` (refresh access token)
- `POST /api/auth/token/verify/` (verify token)
- `GET /api/auth/me/` (identity; JWT required)

Example: obtain token pair

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"pass12345"}'
```

Example: call identity endpoint

```bash
curl -s http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

### User APIs

Mounted in `core/urls.py` (JWT required unless stated otherwise):

#### Identity and orders

- `GET /api/me/` (JWT required; returns the same shape as `/api/auth/me/`)
- `GET /api/orders/me/` (JWT required; lists authenticated user’s paid orders)

#### Wishlist

- `GET /api/wishlist/`
- `POST /api/wishlist/add/` with `{"item_id": <int>}`
- `POST /api/wishlist/remove/` with `{"item_id": <int>}` (idempotent)

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/wishlist/add/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"item_id": 10}'
```

#### Reviews

Public:

- `GET /api/reviews/items/<item_id>/` (AllowAny, visible reviews only)

Authenticated (purchaser-only policy enforced):

- `POST /api/reviews/items/<item_id>/me/` (create/update review; one per user+item)
- `DELETE /api/reviews/items/<item_id>/me/delete/` (delete own review)

Admin moderation:

- `POST /api/reviews/<review_id>/hide/`
- `POST /api/reviews/<review_id>/unhide/`

Example (public list):

```bash
curl -s http://127.0.0.1:8000/api/reviews/items/10/
```

Example (upsert own review):

```bash
curl -s -X POST http://127.0.0.1:8000/api/reviews/items/10/me/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"rating":5,"title":"Great","body":"this is a sufficiently long review"}'
```

### Admin APIs

All admin APIs require JWT + admin role (Admin group OR staff OR superuser).

#### Product management APIs (preferred)

Mounted in `djecommerce/urls.py`:

Categories:

- `GET /api/admin/products/categories/`
- `POST /api/admin/products/categories/`
- `GET /api/admin/products/categories/<category_id>/`
- `PUT/PATCH /api/admin/products/categories/<category_id>/`
- `DELETE /api/admin/products/categories/<category_id>/`

Items:

- `GET /api/admin/products/items/` (includes inactive)
- `POST /api/admin/products/items/`
- `GET /api/admin/products/items/<item_id>/`
- `PUT/PATCH /api/admin/products/items/<item_id>/`
- `DELETE /api/admin/products/items/<item_id>/`

Item soft deactivation:

- `POST /api/admin/products/items/<item_id>/deactivate/` (sets `active=false`)

Inventory management:

- `GET /api/admin/products/items/<item_id>/inventory/`
- `POST /api/admin/products/items/<item_id>/inventory/` with `{"delta": <int>}`

Example: adjust inventory by +5

```bash
curl -s -X POST http://127.0.0.1:8000/api/admin/products/items/10/inventory/ \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"delta": 5}'
```

#### Legacy admin item CRUD

Mounted in `djecommerce/urls.py` and also present in `core/urls.py` for compatibility:

- `GET/POST /api/admin/items/`
- `GET/PUT/PATCH/DELETE /api/admin/items/<item_id>/`

#### Admin order management

Mounted in `core/urls.py`:

- `GET /api/admin/orders/`
- `GET /api/admin/orders/<order_id>/`
- `POST /api/admin/orders/<order_id>/transition/` with `{"new_status":"shipped"}`

Example: transition order to shipped

```bash
curl -s -X POST http://127.0.0.1:8000/api/admin/orders/123/transition/ \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"new_status":"shipped"}'
```

## Order lifecycle (placed → shipped → delivered)

The order lifecycle is implemented explicitly in `core/models.py` on `Order`:

### Status values

- `placed`
- `shipped`
- `delivered`

Field: `Order.status` with enum `Order.OrderStatus`.

### Transition rules

Transitions are linear and forward-only:

- `placed` → `shipped` → `delivered`

Backwards transitions are rejected by `Order.can_transition_to()` and `Order.transition_to()`.

Additionally, unpaid carts are not allowed to be shipped/delivered:

- If `order.ordered == False`, transitions to `shipped` or `delivered` are rejected.

This rule is enforced both:

- at the model method level (`Order.can_transition_to`), and
- in admin transition endpoints (`core/api_views.py` and `core/views.py`).

### Timestamps

Milestone timestamps on `Order`:

- `placed_at`
- `shipped_at`
- `delivered_at`

When a paid order is finalized, the code attempts to mark it as “placed”:

- `_finalize_order_after_successful_payment` in `core/views.py` calls `order.transition_to(Order.OrderStatus.PLACED, ...)` defensively.

### Legacy compatibility

Legacy boolean flags remain and are synced:

- `being_delivered`
- `received`

They are updated in `Order.transition_to()` and `Order.sync_legacy_flags_from_status()`.

## Payments (Stripe): PaymentIntents, webhooks, signature verification, idempotency

### Overview of supported flows

The code supports two payment paths:

1. Preferred: Stripe PaymentIntents flow (Stripe.js on the client, PaymentIntent on server).
2. Fallback: legacy token → Charge flow (kept for template compatibility).

The application does not decrement inventory or finalize the order until Stripe confirms payment success.

### PaymentIntents flow (preferred)

Server-side:

- `PaymentView.get` (`core/views.py`) creates a PaymentIntent with:
  - `amount` = `int(order.get_total() * 100)` (USD cents)
  - `automatic_payment_methods={"enabled": True}`
  - `metadata={"order_id": ..., "user_id": ...}`
  - `idempotency_key=f"order_{order.id}_pi_create"` (prevents duplicate PaymentIntents on refresh)

Client-side:

- The `templates/payment.html` page receives `stripe_payment_intent_client_secret` and calls `stripe.confirmCardPayment(...)`.
- On success, the client POSTs `payment_intent_id` back to `PaymentView.post`.

Server-side finalization:

- `PaymentView.post` retrieves the PaymentIntent and requires `pi["status"] == "succeeded"`.
- Only then does it create a `Payment` record and call `_finalize_order_after_successful_payment`.

### Webhook flow

Endpoint:

- `POST /stripe/webhook/` (mounted in `core/urls.py`)

Handler:

- `core/stripe_webhooks.py` (`stripe_webhook`)

Signature verification:

- If `settings.STRIPE_WEBHOOK_SECRET` is non-empty, the handler calls `stripe.Webhook.construct_event(payload, sig_header, secret)`.
- If empty/missing, it attempts unsigned parsing for local development convenience.

Production guidance: always configure `STRIPE_WEBHOOK_SECRET` and require signature verification. Treat “unsigned accept” as development-only.

Event types processed:

- `payment_intent.succeeded`
- `payment_intent.payment_failed` (records idempotency marker only)

Order linkage:

- The handler expects `metadata.order_id` on the PaymentIntent event object.

### Idempotency notes

Idempotency is enforced in two places:

1. PaymentIntent creation uses Stripe’s `idempotency_key` based on order id.
2. Webhook processing stores the Stripe event id in `Payment.stripe_event_id` (unique). If the event is delivered again, the handler returns `200` and does not decrement stock or finalize again.

This design ensures Stripe retries/replays are “noisy but safe”.

### Test-mode instructions

Local development uses Stripe test keys (development settings). If you have Stripe CLI available, you can forward events to your local server:

```bash
stripe listen --forward-to http://127.0.0.1:8000/stripe/webhook/
```

Use the printed signing secret as `STRIPE_TEST_WEBHOOK_SECRET` in your `.env`.

Test cards are supported by Stripe in test mode (for example `4242 4242 4242 4242` with any future expiry and any CVC).

## Inventory behavior (stock fields, atomic decrement, oversell prevention)

Inventory fields are on `core.models.Item`:

- `track_inventory` (boolean)
- `stock_quantity` (non-negative integer)

### Storefront enforcement

The storefront prevents overselling by validating stock at multiple points:

- When adding to cart (`/add-to-cart/<slug>/`), it blocks increasing quantity beyond `stock_quantity` when `track_inventory` is true.
- Checkout and payment re-validate stock before proceeding (`CheckoutView` and `PaymentView` validate each order item via `Item.ensure_can_fulfill`).

### Atomic decrement on successful payment

Stock decrement happens only after Stripe indicates success, inside a transaction:

- `_finalize_order_after_successful_payment` in `core/views.py` calls:
  - `Item.atomic_decrement_stock_for_order(order)` inside `transaction.atomic()`

`Item.atomic_decrement_stock_for_order` uses:

- `select_for_update()` row locking
- validation against current `stock_quantity`
- `F()` expressions to decrement atomically

If stock is insufficient at finalization time, it raises `ValueError` and the checkout flow is prevented from finalizing.

### Admin inventory adjustment (oversell prevention)

Admin inventory adjustment endpoints also prevent negative stock:

- `POST /api/admin/inventory/adjust/` (legacy) with `{"item_id": <int>, "delta": <int>}`
- `POST /api/admin/products/items/<item_id>/inventory/` (preferred) with `{"delta": <int>}`

Both acquire row locks and reject adjustments that would make stock negative (`400 Bad Request`).

## Testing

### How to run tests

The repository includes a dedicated test settings module:

- `djecommerce/settings/test.py`

Run tests using:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.test python manage.py test
```

This ensures required secrets do not need to be present in CI and uses dummy values for:

- `SECRET_KEY`
- `JWT_SIGNING_KEY`
- Stripe keys and webhook secret

### Stripe mocking notes

Tests mock Stripe calls where appropriate. In `core/test_critical_flows.py`:

- `stripe.PaymentIntent.retrieve` is patched to simulate PaymentIntent states.
- Webhook verification is patched (`stripe.Webhook.construct_event`) to supply a known event payload.

This avoids network calls and makes critical flows deterministic.

### `sitecustomize.py` rationale

The repository contains `sitecustomize.py` at the project root.

Current behavior: it is an intentionally safe no-op placeholder explaining historical compatibility shims for older `django.utils.six` import patterns. The project has since been upgraded to Django 4.2 LTS and modern dependencies that should not require `django.utils.six`, but keeping `sitecustomize.py` avoids surprises in environments that auto-import it.

Source: `sitecustomize.py`.

## Operations runbook (common tasks, rotation, coupons, webhooks, monitoring)

This section is a condensed operator checklist. For more detail, you can also refer to `docs/OPERATIONS_RUNBOOK.md`, but this file is intended to be the primary production-ready operational reference.

### Post-deploy checklist

1. Apply migrations:

```bash
python manage.py migrate
```

2. Bootstrap RBAC:

```bash
python manage.py setup_rbac
```

3. Confirm Stripe configuration:
- The application can create PaymentIntents (for the synchronous flow).
- Webhook endpoint is reachable at `/stripe/webhook/`.
- `STRIPE_WEBHOOK_SECRET` is set and signature verification works.

4. Validate auth boundaries:
- `/accounts/` works for browser login.
- `/api/auth/token/` issues JWTs.
- `/api/auth/me/` returns 200 when called with a valid token.

### Rotating the JWT signing key (considerations)

JWT signing key is `JWT_SIGNING_KEY` (fallback: `SECRET_KEY` if unset). If you rotate it:

- Any previously issued access and refresh tokens will fail verification after rotation (because signature validation changes).
- The repository enables refresh rotation (`ROTATE_REFRESH_TOKENS=True`) but does not enable blacklisting. This means there is no built-in server-side token revocation list; rotation is effectively “hard cutover”.

Recommended operational approach:

1. Ensure production uses a dedicated `JWT_SIGNING_KEY` (not `SECRET_KEY`).
2. Plan for client re-authentication after rotation.
3. Roll the key with a coordinated maintenance window if uninterrupted API sessions matter.

### Managing coupons

Coupon behavior is implemented in `core/models.py`:

- Coupons can be fixed or percent, have validity windows and minimum order totals, and support global/per-user usage limits.
- Redemption accounting is recorded only after payment succeeds (`Order.record_coupon_redemption_if_needed`).

Operational consequences:

- Applying a coupon to a cart does not consume a redemption.
- Only successful paid orders consume redemptions and increment counters.

If you need to change coupon policy, do so carefully and consider DB constraints on redemptions.

### Handling webhooks safely

Webhook endpoint:

- `POST /stripe/webhook/`

Safety requirements:

- Always set `STRIPE_WEBHOOK_SECRET` in production and require signature verification.
- Ensure your reverse proxy forwards the `Stripe-Signature` header intact; without it, signature verification fails.

Idempotency expectations:

- Duplicate deliveries should not double-finalize or double-decrement inventory because `Payment.stripe_event_id` is unique and checked.

### Monitoring and logging suggestions

This repository does not prescribe a logging stack, but production deployments should add:

- Structured request logs for `/stripe/webhook/` (status codes, event id, event type).
- Alerting on webhook `400` responses (invalid payload/signature).
- Metrics/alerts for inventory anomalies (e.g., frequent “insufficient stock” failures during finalization).
- Audit trails for admin transitions (order transitions are model-level operations; consider adding application-level audit logging if required).

## Related documents

- JWT + RBAC decision record: `docs/ADR-001-jwt-rbac.md`
- Authentication and RBAC guide (legacy doc): `docs/AUTH_AND_RBAC.md`
- Features and endpoint catalog (legacy doc): `docs/FEATURES_AND_APIS.md`
- Operations runbook (legacy doc): `docs/OPERATIONS_RUNBOOK.md`
- Setup notes (legacy doc): `docs/SETUP.md`
