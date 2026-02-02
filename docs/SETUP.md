# Setup and Configuration

## Overview

This repository contains a Django 2.2 e-commerce application with server-rendered HTML pages and an API layer. The API layer uses Django REST Framework (DRF) and JWT authentication (SimpleJWT). Template pages continue to use Django sessions via `django-allauth`.

This document describes local development setup and the environment variables used by the application.

## Runtime and compatibility notes

The pinned framework version is Django 2.2 (`Django==2.2.14` in `requirements.txt`). The execution environment for this project may use Python 3.12.

Because Django 2.2-era dependencies (notably older `django-allauth` and `django-countries`) may import `django.utils.six`, the repo includes a compatibility shim at `sitecustomize.py`. Python automatically imports `sitecustomize` at interpreter startup when it is on `sys.path`, which is why it is placed at the project root (next to `manage.py`).

If you run into import errors related to `six`/`django.utils.six` under Python 3.12, ensure you are running from the project root so `sitecustomize.py` is importable.

## Local development setup

### 1) Create and activate a virtual environment

Use any standard Python virtual environment tool (for example, `venv`):

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Create a `.env` file

This project uses `python-decouple` (`decouple.config`) to read environment variables. Create a `.env` file in the project root (same folder as `manage.py`).

If your environment has a `.env.example` file, you should copy it to `.env` and fill in the values. If a `.env.example` is not present, use the variables listed below as your reference.

### 4) Run migrations

```bash
python manage.py migrate
```

### 5) Bootstrap RBAC

This creates/ensures the `Admin` group and grants it permissions used by admin-only endpoints.

```bash
python manage.py setup_rbac
```

### 6) Run the development server

```bash
python manage.py runserver
```

By default, the dev server listens on `http://127.0.0.1:8000/`.

## Settings modules

The project uses a split settings layout:

- `djecommerce/settings/base.py`: shared settings, DRF + JWT configuration
- `djecommerce/settings/development.py`: SQLite and Stripe test keys
- `djecommerce/settings/production.py`: production flags, PostgreSQL settings, Stripe live keys

## Environment variables

### Required variables (always)

#### `SECRET_KEY` (required)
Django secret key used for cryptographic signing.

This must be set for any environment because `djecommerce/settings/base.py` calls `config('SECRET_KEY')` without a default.

Safe default: none. Generate a unique random secret for each environment.

### JWT / DRF variables

#### `JWT_SIGNING_KEY` (optional, strongly recommended in production)
Secret used to sign JWT tokens (SimpleJWT).

- Used by `SIMPLE_JWT['SIGNING_KEY']` in `djecommerce/settings/base.py`.
- If not provided, it defaults to `SECRET_KEY` for backwards-compatible local/dev usage.

Safe default: falls back to `SECRET_KEY` (development convenience). In production, set a dedicated key to allow JWT rotation independent of Django’s `SECRET_KEY`.

### Stripe variables

The code distinguishes test keys (development settings) and live keys (production settings). The webhook signing secret is supported in development and used at runtime by the webhook handler and payment views.

#### Development (test mode)

##### `STRIPE_TEST_PUBLIC_KEY` (required for dev payments)
Used as `STRIPE_PUBLIC_KEY` in `djecommerce/settings/development.py`. Passed into `templates/payment.html` to initialize Stripe.js.

Safe default: none. Obtain from Stripe dashboard (test mode).

##### `STRIPE_TEST_SECRET_KEY` (required for dev payments)
Used as `STRIPE_SECRET_KEY` in `djecommerce/settings/development.py`. Assigned to `stripe.api_key` in `core/views.py`.

Safe default: none. Obtain from Stripe dashboard (test mode).

##### `STRIPE_TEST_WEBHOOK_SECRET` (optional)
Used as `STRIPE_WEBHOOK_SECRET` in `djecommerce/settings/development.py`.

If present, `core/stripe_webhooks.py` will verify incoming webhook signatures. If absent/empty, the webhook handler falls back to parsing an unsigned payload (development-friendly).

Safe default: empty string (`''`), which disables signature verification.

#### Production (live mode)

##### `DEBUG` (required in production settings)
Read by `djecommerce/settings/production.py` and cast to bool.

Safe default: none. Production should normally set `DEBUG=false`.

##### `STRIPE_LIVE_PUBLIC_KEY` (required for live payments)
Used as `STRIPE_PUBLIC_KEY` in `djecommerce/settings/production.py`.

Safe default: none.

##### `STRIPE_LIVE_SECRET_KEY` (required for live payments)
Used as `STRIPE_SECRET_KEY` in `djecommerce/settings/production.py`.

Safe default: none.

> Note: `production.py` does not define a `STRIPE_WEBHOOK_SECRET` variable. If you deploy the webhook handler in production, you should add a webhook secret to your environment and ensure the deployed settings module exposes it as `settings.STRIPE_WEBHOOK_SECRET` (the webhook handler reads that attribute). In this repository, the webhook secret is explicitly configured in `development.py`.

### Database variables (production)

The production settings are wired for PostgreSQL and require:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`

Safe defaults: none. These must be configured for a production deployment using `djecommerce/settings/production.py`.

## Common local smoke checks

### Storefront page

Open:

- `GET /` (home page / product listing)

### JWT authentication smoke check

Obtain an access/refresh token pair:

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<user>","password":"<pass>"}'
```

Call the protected identity endpoint:

```bash
curl -s http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```
