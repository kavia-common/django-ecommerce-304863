# Operations Runbook

## Overview

This runbook is intended for operators deploying and maintaining the Django e-commerce application. It covers post-deploy checks, RBAC bootstrapping, Stripe webhook operations, and security considerations.

## Deployment checklist

### 1) Environment variables

Before deploying, ensure you have configured at least:

- `SECRET_KEY`
- Stripe keys appropriate for the environment (`STRIPE_LIVE_*` or `STRIPE_TEST_*`)
- database credentials if using `djecommerce/settings/production.py`
- `JWT_SIGNING_KEY` (recommended in production)

See `docs/SETUP.md` for the full list and behavior of defaults.

### 2) Database migrations

Run migrations on the deployed environment:

```bash
python manage.py migrate
```

### 3) RBAC bootstrap

Run the RBAC setup command after migrations (or whenever a new environment is created):

```bash
python manage.py setup_rbac
```

This ensures the `Admin` group exists and has the relevant `Item` and `Order` permissions.

### 4) Static/media handling

This repository is configured with:

- `STATICFILES_DIRS` pointing to `static_in_env`
- `STATIC_ROOT` and `MEDIA_ROOT` for collected/static and uploaded media

In production, you typically want to serve static and media via a proper static file server/CDN. This repository does not include a full production static pipeline; treat the settings as a baseline.

## Post-deploy smoke tests

### 1) Storefront loads

Verify the home page renders:

- `GET /`

### 2) JWT token issuance works

Verify the token endpoint responds:

- `POST /api/auth/token/`

Example:

```bash
curl -i -X POST https://<host>/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<user>","password":"<pass>"}'
```

### 3) JWT-protected identity endpoint works

- `GET /api/auth/me/`

Example:

```bash
curl -i https://<host>/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

Expected: `200 OK` with basic identity JSON.

### 4) Admin-only API protection works

Call an admin endpoint with a normal token and confirm `403`, then with an admin token and confirm `200`:

- `GET /api/admin/items/`

This validates both JWT auth and the RBAC permission boundary.

## Stripe webhook operations

### Webhook endpoint

The webhook route is:

- `POST /stripe/webhook/`

It is CSRF-exempt by design because it is called by Stripe.

### Signature verification behavior

The handler reads `settings.STRIPE_WEBHOOK_SECRET`.

- If the secret is configured (non-empty), it verifies the signature using Stripe’s library.
- If the secret is missing/empty, it accepts unsigned events and attempts to parse them. This is convenient for local development but is not appropriate for a hardened production environment.

Operational guidance:

- In any real deployment that accepts internet traffic, configure a webhook signing secret and ensure it is exposed as `STRIPE_WEBHOOK_SECRET` in the runtime settings module.

### Idempotency and replay handling

Idempotency is enforced by storing the Stripe event id in:

- `Payment.stripe_event_id` (unique)

If Stripe retries delivery (or you replay events), the handler will:

- return `200 OK`
- not decrement inventory again
- not finalize the order again

Operational expectation:

- Duplicate deliveries should be “noisy but safe”.
- The correct steady-state is exactly one `Payment` row with a given event id.

### Rotating the webhook secret

To rotate the webhook secret:

1. Create a new webhook endpoint secret in Stripe (or update your endpoint configuration).
2. Update the deployed environment variable (or secrets manager) that provides `STRIPE_WEBHOOK_SECRET`.
3. Restart the application if required by your deployment platform so the new setting takes effect.
4. Confirm delivery succeeds by observing:
   - a `200` response from the webhook
   - order finalization for a test PaymentIntent event

### Stripe CLI (optional)

If Stripe CLI is available, you can forward events to your deployment for verification during maintenance windows.

For local environments, Stripe CLI forwarding is the simplest way to obtain and validate webhook secrets.

## Security notes

### Secrets management

- Do not commit `.env` files or secrets to version control.
- `SECRET_KEY`, `JWT_SIGNING_KEY`, and Stripe secret keys must be stored in a proper secrets store for production.

### JWT token lifetimes

Default JWT lifetimes are configured in `djecommerce/settings/base.py`:

- access tokens are short-lived (minutes)
- refresh tokens are longer-lived (days) and rotated

Operational guidance:

- Treat access tokens as ephemeral and assume leakage risk exists; short TTL reduces the blast radius.
- If you need tighter controls (revocation/blacklisting), you would add SimpleJWT blacklist support; it is not enabled in this repository.

### Staff/admin access control

Admin role is granted if:

- user is `is_staff` OR `is_superuser` OR in group `Admin`

Operational guidance:

- Keep admin privileges limited.
- Prefer group-based access (`Admin` group) for clarity and auditing.

### CSRF considerations

- Template flows use Django CSRF middleware. Ensure CSRF remains enabled for browser traffic.
- API flows rely on Bearer tokens and are not intended for cookie-based authentication.
- The webhook endpoint is CSRF-exempt and should be protected by Stripe signature verification in production.

## Incident response notes

### Symptoms: inventory went negative or oversold

The code attempts to prevent negative inventory by:

- row locking
- validating stock before decrement
- rejecting admin adjustments that would go negative

If oversell occurs, it often indicates:
- inventory tracking disabled (`track_inventory=false`) for the item, or
- manual DB edits, or
- checkout was finalized through an unexpected path

Immediate actions:
1. Disable sales for the affected item (`active=false`).
2. Correct `stock_quantity` via admin inventory endpoints.
3. Review logs around payment finalization and webhook deliveries.

### Symptoms: webhook processing fails

The webhook returns `400` for invalid payload or signature failure.

Immediate actions:
1. Confirm `STRIPE_WEBHOOK_SECRET` matches Stripe’s configured signing secret.
2. Confirm Stripe is calling the correct URL path `/stripe/webhook/`.
3. If using a reverse proxy, confirm it is not stripping headers (Stripe signature header is required for verification).

## Testing and validation in ops

For a quick verification after deployment changes:

```bash
python manage.py test
```

The repository includes critical-flow tests that cover:

- JWT obtain/verify/refresh and authenticated `/api/auth/me/`
- RBAC restrictions for admin endpoints
- inventory validation and atomic decrement
- order lifecycle transitions
- Stripe webhook idempotency behavior
- wishlist, reviews, and coupons flows
