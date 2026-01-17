<p align="center">
  <p align="center">
    <a href="https://justdjango.com/?utm_source=github&utm_medium=logo" target="_blank">
      <img src="https://assets.justdjango.com/static/branding/logo.svg" alt="JustDjango" height="72">
    </a>
  </p>
  <p align="center">
    The Definitive Django Learning Platform.
  </p>
</p>

### *** Deprecation warning ***

This project was created almost two years ago. Since then, there is a newer version of the project which you can find [here](https://github.com/justdjango/django-simple-ecommerce)

---

# Django E-commerce

This is a very simple e-commerce website built with Django.

## Quick demo

[![alt text](https://justdjango.s3-us-west-2.amazonaws.com/media/gifs/djecommerce.gif "Logo")](https://youtu.be/z4USlooVXG0)

---

## Project Summary

The website displays products. Users can add and remove products to/from their cart while also specifying the quantity of each item. They can then enter their address and choose Stripe to handle the payment processing.

[![alt text](https://justdjango.s3-us-west-2.amazonaws.com/media/thumbnails/djecommerce.png "Logo")](https://youtu.be/z4USlooVXG0)

---

## Running this project

To get this project up and running you should start by having Python installed on your computer. It's advised you create a virtual environment to store your projects dependencies separately. You can install virtualenv with

```
pip install virtualenv
```

Clone or download this repository and open it in your editor of choice. In a terminal (mac/linux) or windows terminal, run the following command in the base directory of this project

```
virtualenv env
```

That will create a new folder `env` in your project directory. Next activate it with this command on mac/linux:

```
source env/bin/active
```

Then install the runtime (production) dependencies with

```
pip install -r requirements.txt
```

If you're developing locally (linting/formatting/debug tooling), also install dev-only dependencies with

```
pip install -r requirements-dev.txt
```

Create your environment variables by copying the example file:

```
cp .env.example .env
```

Now you can run the project with this command

```
python manage.py runserver
```

**Note**: payments require valid Stripe keys in `.env` (see `.env.example`).

---

## Production Setup

This project includes hardened production settings at `djecommerce/settings/production.py`. Those settings are intentionally **fail-safe**: they will raise an error on startup rather than run insecurely or with placeholder values.

### Required environment variables (production)

Set these in your production environment (or via a secret manager). These are required by `production.py`:

- `DEBUG` — **must be explicitly** `False`
- `SECRET_KEY` — Django secret key (long, random, unique)
- `ALLOWED_HOSTS` — comma-separated domains, e.g. `example.com,www.example.com`
  - Must not be empty and must not be placeholder values like `example.com`, `yourdomain.com`, etc.
- Database (PostgreSQL):
  - `DB_NAME`
  - `DB_USER`
  - `DB_PASSWORD`
  - `DB_HOST`
  - `DB_PORT` (optional)
- Stripe (live mode):
  - `STRIPE_LIVE_PUBLIC_KEY`
  - `STRIPE_LIVE_SECRET_KEY`
- `SECURE_SSL_REDIRECT` (optional) — defaults to `True` in production settings. Set to `False` only if you know what you're doing (e.g., specific staging setups).

### Security defaults already enabled in `production.py`

The production settings already turn on common secure defaults, including:

- Secure cookies / session protections:
  - `SESSION_COOKIE_SECURE = True`
  - `CSRF_COOKIE_SECURE = True`
  - `SESSION_COOKIE_HTTPONLY = True`
  - `SameSite` set to `Lax` for session/CSRF cookies
- HTTPS enforcement & HSTS:
  - `SECURE_SSL_REDIRECT` enabled by default
  - HSTS enabled (`SECURE_HSTS_SECONDS`, `INCLUDE_SUBDOMAINS`, `PRELOAD`)
- Clickjacking / content-type protections:
  - `X_FRAME_OPTIONS = "DENY"`
  - `SECURE_CONTENT_TYPE_NOSNIFF = True`
- Reverse proxy HTTPS awareness:
  - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
  - Ensure your proxy/load balancer sets `X-Forwarded-Proto: https`

### Example `.env.production` (do not commit)

Create an environment file (or set these vars in your platform’s secret manager). **Never commit real production secrets to git.**

```bash
# Django
DEBUG=False
SECRET_KEY="django-insecure-CHANGE-ME-use-a-50+-char-random-secret"
ALLOWED_HOSTS="shop.example.com,www.shop.example.com"

# Database (PostgreSQL)
DB_NAME="djecommerce"
DB_USER="djecommerce_user"
DB_PASSWORD="a-strong-db-password"
DB_HOST="127.0.0.1"
DB_PORT="5432"

# Stripe (LIVE)
STRIPE_LIVE_PUBLIC_KEY="pk_live_xxxxxxxxxxxxxxxxxxxxx"
STRIPE_LIVE_SECRET_KEY="sk_live_xxxxxxxxxxxxxxxxxxxxx"

# Optional override (default in production.py is True)
SECURE_SSL_REDIRECT=True
```

### Basic deployment steps (typical)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Export/set your production environment variables (or load them via your process manager).
3. Collect static files:
   ```bash
   python manage.py collectstatic --noinput
   ```
4. Run migrations:
   ```bash
   python manage.py migrate
   ```
5. (Optional) Create an admin user:
   ```bash
   python manage.py createsuperuser
   ```
6. Run the app with Gunicorn (example):
   ```bash
   gunicorn djecommerce.wsgi:application
   ```

> Note: Your actual Gunicorn command may vary depending on your platform (systemd, Docker, Heroku-like, etc.). Ensure your environment variables are present for the running process.

### Fail-fast misconfiguration warning

When using `djecommerce/settings/production.py`, the app will **refuse to start** if:

- `DEBUG` is not explicitly set to `False`, or
- `ALLOWED_HOSTS` is missing/empty or contains common placeholder domains, or
- required secrets (like `SECRET_KEY`, database variables, or Stripe live keys) are missing.

This is expected and is there to prevent insecure deployments.

### Stripe key management

- Use your hosting provider’s **secret manager** / encrypted env vars for Stripe keys.
- Never commit Stripe keys (live or test) into the repository.
- Rotate keys immediately if you suspect exposure.

---

## Auto-reconcile loop (every 5 minutes)

This repository includes an optional, preview-safe auto-reconcile script that can run a cron-like loop every 5 minutes. It is designed to:
- analyze this local Django repo plus the remote Flasky repo metadata (without cloning/vendoring Flasky),
- regenerate selected manifests (currently `requirements.txt` and `.env.example` are normalized/idempotently rewritten),
- write a small state file at `.autogen/state.json` including the last run timestamp, Flasky commit ref used, and a summary of file changes.

### Run once (on-demand)

From the `django-ecommerce-304863/` directory:

```
python scripts/auto_reconcile.py run
```

Optional flags:
- `--dry-run` to preview changes without writing files
- `--verbose` for more detailed logs

Example:

```
python scripts/auto_reconcile.py --dry-run --verbose run
```

### Run continuously (loop)

```
python scripts/auto_reconcile.py loop --interval-seconds 300
```

Stop it with Ctrl+C.

### Disable

Simply do not run the script (there is no background daemon). The loop only runs when explicitly started.

### Inspect last run

```
python scripts/auto_reconcile.py status
```

---

## Follow the tutorial

This project is part of a [series on YouTube](https://youtu.be/z4USlooVXG0) that teaches how to build an e-commerce website with Django.

---

## Support

If you'd like to support this project and all the other open source work on this organization, you can use the following options

### Option 1: GitHub Sponsors

Sponsor through GitHub Sponsors. On GitHub, [this repository](https://github.com/justdjango/django-ecommerce) shows a button where you can Sponsor the contributors.

### Option 2: JustDjango

If you're learning Django and want to take your next step to become a professional Django developer, consider signing up on [JustDjango](https://learn.justdjango.com).

---

<div align="center">

<i>Other places you can find us:</i><br>

<a href="https://www.youtube.com/channel/UCRM1gWNTDx0SHIqUJygD-kQ" target="_blank"><img src="https://img.shields.io/badge/YouTube-%23E4405F.svg?&style=flat-square&logo=youtube&logoColor=white" alt="YouTube"></a>
<a href="https://www.twitter.com/justdjangocode" target="_blank"><img src="https://img.shields.io/badge/Twitter-%231877F2.svg?&style=flat-square&logo=twitter&logoColor=white" alt="Twitter"></a>

</div>
