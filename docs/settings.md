# Settings & environment variables

This project reads configuration from environment variables (commonly via a local `.env` file).  
Production settings are hardened and validated at import time to fail fast when critical variables are missing or unsafe.

## Environment selection

- `ENVIRONMENT` (default: `local`)
  - Supported values: `local`, `development`, `production`

## Debug / secret key validation

- `DEBUG` (default: `False`)
  - If `ENVIRONMENT=production` and `DEBUG=True`, Django will raise `ImproperlyConfigured` and refuse to start.

- `SECRET_KEY`
  - Required when `ENVIRONMENT=production`.
  - Recommended for all environments.

## Hosts / CSRF / CORS

- `ALLOWED_HOSTS`
  - Accepts JSON list or comma/whitespace-separated list.
  - Example: `ALLOWED_HOSTS=example.com,.example-preview.com`
  - Production validation: must not be empty and must not contain `*`.

- `PREVIEW_ALLOWED_HOST_SUFFIXES` (optional)
  - List of suffixes to allow wildcard subdomains safely.
  - Example: `.kavia.app,.vercel.app` (leading dot is normalized)
  - Result: adds `".kavia.app"` / `".vercel.app"` to `ALLOWED_HOSTS`.

- `CSRF_TRUSTED_ORIGINS` (optional)
  - List of full origins (scheme + host).
  - Example: `https://example.com,https://admin.example.com`

- `CORS_ALLOWED_ORIGINS` (optional)
  - If set (non-empty), CORS middleware is enabled via `django-cors-headers`.
  - Example: `https://app.example.com`

## Security toggles (recommended for production)

Defaults are secure-on when `ENVIRONMENT=production`:

- `SECURE_SSL_REDIRECT` (default: `True` in production)
- `SECURE_HSTS_SECONDS` (default: `31536000` in production)
- `SECURE_HSTS_INCLUDE_SUBDOMAINS` (default: `True` in production)
- `SECURE_HSTS_PRELOAD` (default: `True` in production)
- `SESSION_COOKIE_SECURE` (default: `True` in production)
- `CSRF_COOKIE_SECURE` (default: `True` in production)

Cookie hardening (optional overrides):

- `SESSION_COOKIE_SAMESITE` (default: `Lax`)
- `CSRF_COOKIE_SAMESITE` (default: `Lax`)
- `SESSION_COOKIE_HTTPONLY` (default: `True`)
- `CSRF_COOKIE_HTTPONLY` (default: `False`)

Reverse proxy support:

- `USE_X_FORWARDED_PROTO` (default: `False`)
  - If `True`, sets `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')`.

## Logging

- `LOG_LEVEL` (default: `INFO`)
- `LOG_FORMAT` (default: `text`, supports `json`)
  - JSON output is dependency-free and works with gunicorn/container logging.

## Database

- `DATABASE_URL` (optional)
  - If set, overrides production DB settings.
  - Supported without additional dependencies: Postgres URLs only  
    `postgres://USER:PASSWORD@HOST:PORT/DBNAME`

## Payments

- `PAYMENT_MODE` (default: `dummy`)
  - `dummy` (default) does not require Stripe keys.
  - `stripe` will use Stripe keys if present.
  - Production validation: if `PAYMENT_MODE=stripe`, Stripe keys become required.

Stripe keys (required only when `PAYMENT_MODE=stripe` in production):

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLIC_KEY`
