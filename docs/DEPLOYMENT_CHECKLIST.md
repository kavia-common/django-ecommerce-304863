# Deployment Checklist (Production) — Django E-commerce

## Overview

This checklist is a practical, production-focused guide for deploying this repository’s Django e-commerce application. It is tailored to the current codebase layout, settings modules, and integrations, including DRF + SimpleJWT, RBAC, CSP headers, and Stripe PaymentIntents + webhooks.

This project’s settings are split across:

- `djecommerce/settings/base.py` (shared defaults, security toggles, CSP, DRF/JWT, logging)
- `djecommerce/settings/production.py` (PostgreSQL, production security defaults, Stripe live keys)
- `djecommerce/settings/test.py` (CI-friendly dummy secrets)

## 1) Environment and dependencies

### 1.1 Pin versions and install requirements

The repository is pinned (Python 3.12 compatible) in `requirements.txt` (Django 4.2 LTS and related packages).

Commands:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.2 Set production settings module

The production settings module is `djecommerce.settings.production`.

You must ensure the runtime uses it, because `manage.py` defaults to development:

- `manage.py` sets `DJANGO_SETTINGS_MODULE` to `djecommerce.settings.development` by default.
- Production processes should explicitly set `DJANGO_SETTINGS_MODULE=djecommerce.settings.production`.

Example:

```bash
export DJANGO_SETTINGS_MODULE=djecommerce.settings.production
```

If using Gunicorn:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production gunicorn djecommerce.wsgi:application
```

### 1.3 Required environment variables (production)

This project reads configuration via `python-decouple` (`decouple.config`) in `djecommerce/settings/base.py` and `djecommerce/settings/production.py`. Ensure these variables are present in your deployment environment (Kubernetes secrets, ECS task env, systemd EnvironmentFile, etc.).

#### Core Django / runtime

- `SECRET_KEY` (required): Django signing key (`base.py` reads `SECRET_KEY = config('SECRET_KEY')`).
- `DEBUG` (required in production settings): `production.py` reads `DEBUG = config('DEBUG', cast=bool)`.

Operational guidance: set `DEBUG=false` in production.

#### Hosts, proxy, and CSRF origins (recommended in production)

From `djecommerce/settings/base.py`:

- `DJANGO_ALLOWED_HOSTS` (comma-separated): populates `ALLOWED_HOSTS`.
- `DJANGO_CSRF_TRUSTED_ORIGINS` (comma-separated): populates `CSRF_TRUSTED_ORIGINS`.
- `DJANGO_SECURE_PROXY_SSL_HEADER` (string): only needed when running behind a TLS-terminating proxy.
  - Format: `HTTP_X_FORWARDED_PROTO,https`.

Also note: `djecommerce/settings/production.py` has a fallback `ALLOWED_HOSTS = ['ip-address', 'www.your-website.com']` if `ALLOWED_HOSTS` was not already set. In a real deployment, you should explicitly set `DJANGO_ALLOWED_HOSTS`.

#### Database (PostgreSQL)

From `djecommerce/settings/production.py`:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`

Note: production settings set `PORT` to an empty string in code; if you need a non-default port, you will need to adapt deployment/code accordingly.

#### JWT / API auth (recommended separate key)

From `djecommerce/settings/base.py`:

- `JWT_SIGNING_KEY` (recommended in production)
  - If unset, the code falls back to `SECRET_KEY`, but production should set a dedicated signing key.

Important naming note: the implementation uses `JWT_SIGNING_KEY` (not `JWT_SECRET_KEY`).

#### Stripe payments and webhooks

From `djecommerce/settings/production.py` (live keys):

- `STRIPE_LIVE_PUBLIC_KEY` (required): mapped to `STRIPE_PUBLIC_KEY`.
- `STRIPE_LIVE_SECRET_KEY` (required): mapped to `STRIPE_SECRET_KEY`.
- `STRIPE_WEBHOOK_SECRET` (strongly recommended): used by the webhook handler (`core/stripe_webhooks.py`) to verify signatures.

Webhook signature verification behavior:

- If `STRIPE_WEBHOOK_SECRET` is non-empty, the webhook verifies `Stripe-Signature`.
- If empty, it falls back to unsigned event parsing (convenient for local development, not appropriate for production).

#### Security flags (HTTPS enforcement and cookies)

From `djecommerce/settings/base.py` and `djecommerce/settings/production.py`:

- `DJANGO_SECURE_SSL_REDIRECT` (bool)
- `DJANGO_SECURE_HSTS_SECONDS` (int; recommended 31536000 in production)
- `DJANGO_SESSION_COOKIE_SECURE` (bool)
- `DJANGO_CSRF_COOKIE_SECURE` (bool)

`production.py` defaults these to secure values (SSL redirect + secure cookies + 1-year HSTS) unless overridden.

#### CSP (django-csp) configuration

From `djecommerce/settings/base.py` and `production.py`:

- `DJANGO_CSP_REPORT_ONLY` (bool)
  - Production should typically be enforcing: `DJANGO_CSP_REPORT_ONLY=false`.

Optional allowlist extension variables (comma-separated), if you add additional third-party resources:

- `DJANGO_CSP_ADDITIONAL_SCRIPT_SRC`
- `DJANGO_CSP_ADDITIONAL_STYLE_SRC`
- `DJANGO_CSP_ADDITIONAL_CONNECT_SRC`
- `DJANGO_CSP_ADDITIONAL_IMG_SRC`
- `DJANGO_CSP_ADDITIONAL_FRAME_SRC`

Baseline CSP already allows Stripe’s required domains:

- `https://js.stripe.com` (script/frame)
- `https://api.stripe.com` (connect)

#### DRF throttling

From `djecommerce/settings/base.py`:

- `DRF_THROTTLE_ANON` (default `60/min`)
- `DRF_THROTTLE_USER` (default `600/min`)

#### Logging level controls

From `djecommerce/settings/base.py`:

- `DJANGO_LOG_LEVEL` (default `INFO`)
- `DJANGO_SECURITY_LOG_LEVEL` (default `WARNING`)

## 2) Database and migrations

### 2.1 Apply migrations (required)

Run migrations during deploy (or as a release step) with production settings:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production python manage.py migrate
```

### 2.2 Collect static files (required for production serving)

This project defines:

- `STATICFILES_DIRS = [<repo>/static_in_env]`
- `STATIC_ROOT = <repo>/static_root`

Collect static:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production python manage.py collectstatic --noinput
```

### 2.3 Bootstrap RBAC (required for new environments)

This project expects an `Admin` group to exist with permissions. Run:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production python manage.py setup_rbac
```

This command is implemented in `core/management/commands/setup_rbac.py`.

### 2.4 Create a superuser (recommended)

For Django admin UI (`/admin/`) and operator access:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production python manage.py createsuperuser
```

### 2.5 Backup/restore notes (operator guidance)

Database backup is deployment-platform dependent, but the operational requirement is consistent:

- Before major migrations or releases, take a DB backup snapshot.
- Ensure you can restore in a staging environment to validate.

If you use `pg_dump`:

```bash
pg_dump --format=custom --file backup.dump "$DATABASE_URL"
```

Restore example:

```bash
pg_restore --clean --no-owner --dbname "$DATABASE_URL" backup.dump
```

Media backup is also required if `MEDIA_ROOT` is stored on disk; see the static/media section below.

## 3) Static and media files

### 3.1 Static files

In settings (`djecommerce/settings/base.py`):

- `STATICFILES_DIRS` points to `static_in_env` (source assets inside the repo).
- `STATIC_ROOT` is `static_root` (collectstatic output).

Production options:

1. Serve `STATIC_ROOT` via Nginx (common in VM deployments).
2. Use a CDN/object-store workflow (upload the contents of `STATIC_ROOT` after `collectstatic`).

This repository does not include a staticfiles middleware such as Whitenoise. If you choose to use Whitenoise, you would need to add it in code/settings; do not assume it is enabled.

### 3.2 Media files

In settings (`djecommerce/settings/base.py`):

- `MEDIA_ROOT = <repo>/media_root`
- `MEDIA_URL = /media/`

Important behavior: `djecommerce/urls.py` only serves static/media from Django when `DEBUG` is true. In production, you must serve media via:

- Nginx (filesystem-backed media), or
- object storage (S3/GCS/etc.) with Django storage backend changes (not present by default).

Operator guidance: treat media as persistent state, not ephemeral container disk, unless you intentionally accept data loss.

## 4) Security and HTTPS

### 4.1 Enforce HTTPS at Django level

Production defaults already set this (unless overridden), but confirm:

- `SECURE_SSL_REDIRECT` should be enabled.
- `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` should be enabled.
- HSTS should be enabled (after confirming HTTPS works correctly).

Relevant settings are in:

- `djecommerce/settings/base.py`
- `djecommerce/settings/production.py`

Suggested production env:

```bash
export DJANGO_SECURE_SSL_REDIRECT=true
export DJANGO_SESSION_COOKIE_SECURE=true
export DJANGO_CSRF_COOKIE_SECURE=true
export DJANGO_SECURE_HSTS_SECONDS=31536000
```

### 4.2 Proxy headers (TLS terminated upstream)

If your reverse proxy/ingress terminates TLS and forwards requests to Django over HTTP, configure:

```bash
export DJANGO_SECURE_PROXY_SSL_HEADER="HTTP_X_FORWARDED_PROTO,https"
```

Ensure your proxy sets `X-Forwarded-Proto: https` and that it is not spoofable from the public internet (only trusted internal traffic should reach Django).

### 4.3 Allowed hosts and CSRF trusted origins

Set host and origin allowlists explicitly:

```bash
export DJANGO_ALLOWED_HOSTS="yourdomain.com,www.yourdomain.com"
export DJANGO_CSRF_TRUSTED_ORIGINS="https://yourdomain.com,https://www.yourdomain.com"
```

### 4.4 CSP (django-csp) in enforcing mode

This project includes `csp.middleware.CSPMiddleware` and CSP directives in `base.py`. Production should generally enforce CSP, not run report-only:

```bash
export DJANGO_CSP_REPORT_ONLY=false
```

If you add additional third-party scripts/styles, extend via the `DJANGO_CSP_ADDITIONAL_*` variables rather than weakening the baseline policy.

## 5) Application server and reverse proxy

### 5.1 WSGI entrypoint

WSGI app is `djecommerce.wsgi:application` (`djecommerce/wsgi.py`).

### 5.2 Example Gunicorn command

A common baseline (tune workers based on CPU/memory and request latency):

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.production \
gunicorn djecommerce.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --threads 2 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile -
```

Notes:

- Prefer running Gunicorn behind a reverse proxy (Nginx/ALB/Ingress) rather than exposing it directly.
- Use platform-specific process management (systemd, supervisord, container orchestrator).

### 5.3 Nginx (or equivalent) reverse proxy essentials

At minimum, ensure:

- TLS termination is enabled (Let’s Encrypt or managed certs).
- Proxy headers include `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto`.
- Static files (`STATIC_ROOT`) are served directly by Nginx.
- Media files (`MEDIA_ROOT`) are served directly if using filesystem-backed media.

Also ensure the proxy forwards the Stripe signature header:

- `Stripe-Signature` must reach Django for webhook verification.

## 6) Logging and monitoring

### 6.1 Django application logs

A baseline LOGGING config exists in `djecommerce/settings/base.py` and logs to console with configurable levels. In production, capture stdout/stderr via your platform (Docker logs, journald, etc.).

Set desired levels:

```bash
export DJANGO_LOG_LEVEL=INFO
export DJANGO_SECURITY_LOG_LEVEL=WARNING
```

If you need structured/JSON logs, implement them in settings (not present by default). The operational principle is to emit structured logs at the process boundary so your log collector can parse them reliably.

### 6.2 Proxy access logs

Enable access logs at your reverse proxy/load balancer for:

- `GET /` and other storefront routes (baseline traffic)
- `POST /stripe/webhook/` (critical; alert on 400 responses)
- `/api/**` endpoints (especially admin endpoints)

### 6.3 Error monitoring (recommended)

This repository does not include an error monitoring SDK by default, but production deployments should adopt one (for example Sentry) to capture:

- unhandled exceptions
- performance regressions (optional)
- elevated 5xx rates

### 6.4 Health checks

This repository does not define a dedicated `/health/` endpoint. For platform health checks, use a low-cost existing endpoint, typically:

- `GET /` (storefront home page), or
- `GET /api/auth/me/` only if you can supply a token (usually not practical for a generic liveness probe)

Recommended approach if you need a strict health endpoint: add an explicit health view in code. Until then, use `GET /` and alert on non-200 status.

## 7) Payments and webhooks (Stripe)

### 7.1 Confirm key configuration

Production settings (`djecommerce/settings/production.py`) read:

- `STRIPE_LIVE_PUBLIC_KEY` → `STRIPE_PUBLIC_KEY`
- `STRIPE_LIVE_SECRET_KEY` → `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET` → `STRIPE_WEBHOOK_SECRET`

Ensure these are set in production environment variables/secrets.

### 7.2 Webhook endpoint path

The Stripe webhook handler is implemented in `core/stripe_webhooks.py`. The endpoint is mounted at:

- `POST /stripe/webhook/` (it is registered in `core/urls.py`, which is included by `djecommerce/urls.py`)

Configure your Stripe Dashboard webhook endpoint to the full URL:

- `https://<your-domain>/stripe/webhook/`

### 7.3 Verify signature verification works

In production you should require signature verification. Ensure:

- `STRIPE_WEBHOOK_SECRET` is set (non-empty).
- Your reverse proxy forwards `Stripe-Signature`.

Validation steps:

1. Trigger a test event in Stripe dashboard (or Stripe CLI).
2. Confirm your application returns `200`.
3. Confirm logs show processing (and no `400` from signature errors).

### 7.4 Idempotency notes (operational impact)

Webhook processing is designed to be idempotent by storing Stripe’s event id in `Payment.stripe_event_id` (unique). Duplicate deliveries should return `200` and should not double-finalize an order.

Operationally, treat repeated deliveries as normal and alert only when:

- webhook starts returning `400`, or
- paid orders do not finalize (business symptom).

## 8) Ops runbooks

### 8.1 Safe rollout strategy for migrations

For typical schema migrations:

1. Deploy code that is backwards compatible with current schema.
2. Run migrations.
3. Deploy code that depends on the new schema (if needed).

At minimum, avoid long-running locking migrations during peak traffic and always take a DB backup first.

### 8.2 Key rotation notes (JWT and Django)

JWT signing:

- Setting is `JWT_SIGNING_KEY` (falls back to `SECRET_KEY` if unset).
- Rotating `JWT_SIGNING_KEY` invalidates existing JWTs immediately (clients will need to re-authenticate).

Django secret key (`SECRET_KEY`):

- Rotating `SECRET_KEY` affects Django’s signing and sessions. Plan rotation carefully, as it can invalidate sessions and other signed data.

### 8.3 CI / tests command

The repository includes a test settings module intended for CI:

- `djecommerce.settings.test`

Run tests in CI:

```bash
DJANGO_SETTINGS_MODULE=djecommerce.settings.test python manage.py test
```

### 8.4 Backup/restore (DB and media)

Minimum operator requirement:

- DB: periodic snapshots and pre-release backup.
- Media: snapshot/copy of `media_root` if filesystem-based, or ensure object-storage versioning/lifecycle policy if using S3/GCS.

## 9) Post-deploy verification checklist

### 9.1 Infrastructure-level checks

- [ ] DNS resolves to the correct load balancer / host.
- [ ] TLS certificate is valid and auto-renewal is configured.
- [ ] HTTP redirects to HTTPS (if enabled).
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are correct for the domain.
- [ ] Proxy forwarding is correct (`X-Forwarded-Proto` and `Host`).

### 9.2 Django startup and migrations

- [ ] App boots with `DJANGO_SETTINGS_MODULE=djecommerce.settings.production`.
- [ ] `python manage.py migrate` completed successfully.
- [ ] `python manage.py collectstatic --noinput` completed successfully.
- [ ] `python manage.py setup_rbac` completed successfully.
- [ ] A superuser exists (if you need Django admin UI).

### 9.3 Smoke tests (storefront)

- [ ] Home page loads: `GET /`
- [ ] Product detail page loads (pick an existing product): `GET /products/<slug>/` (path depends on existing catalog/URLs)
- [ ] Add to cart works (browser flow).
- [ ] Checkout page loads for an authenticated user.
- [ ] Payment page loads and renders Stripe.js without CSP violations.

### 9.4 Payments and order lifecycle (test carefully)

In a staging environment (recommended), confirm:

- [ ] PaymentIntent can be created (checkout → payment page).
- [ ] Webhook endpoint is reachable and returns `200` on Stripe test delivery.
- [ ] Successful payment finalizes order and decrements stock once (idempotency behavior).

### 9.5 API checks (JWT + RBAC)

JWT auth endpoints are mounted in `djecommerce/urls.py`:

- [ ] Obtain token: `POST /api/auth/token/`
- [ ] Verify identity with token: `GET /api/auth/me/`

Admin APIs are under `/api/admin/**` and require JWT + admin role (Admin group or staff or superuser):

- [ ] With a non-admin token, an admin endpoint returns `403` (for example `GET /api/admin/items/`).
- [ ] With an admin token, the same endpoint returns `200`.

Example commands:

```bash
# Obtain JWT
curl -s -X POST https://<host>/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<user>","password":"<pass>"}'

# Call identity endpoint
curl -i https://<host>/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"

# Call an admin endpoint (should be 403 for non-admin)
curl -i https://<host>/api/admin/items/ \
  -H "Authorization: Bearer <access_token>"
```
