# Authentication and RBAC

## Overview

This project intentionally supports two authentication modes at the same time:

1. Session-based authentication for browser/template flows via `django-allauth` and Django sessions.
2. JWT-based authentication for API clients via Django REST Framework and SimpleJWT.

The goal is to keep the existing server-rendered storefront working as-is, while enabling programmatic API access and admin-only API surfaces.

## Session authentication (templates)

### What it is used for

Template-rendered routes (for example `/`, `/checkout/`, `/payment/stripe/`, `/my/orders/`, `/wishlist/`) use Django’s standard session authentication. Login/registration is provided under:

- `/accounts/` (allauth)

### Security boundary

Session requests rely on:

- Django sessions (`django.contrib.sessions`)
- CSRF protection (`django.middleware.csrf.CsrfViewMiddleware`) for state-changing form posts

This is appropriate for browser-based flows. API clients should generally not use session auth in this project because the DRF configuration is JWT-only by default.

## JWT authentication (API)

### What it is used for

All `/api/**` endpoints are implemented with Django REST Framework and require authentication unless explicitly marked `AllowAny`.

In `djecommerce/settings/base.py`, DRF is configured as:

- Authentication: `rest_framework_simplejwt.authentication.JWTAuthentication`
- Default permission: `rest_framework.permissions.IsAuthenticated`

This means:
- API requests without a valid JWT will generally return `401 Unauthorized`.
- Admin-only API routes also apply RBAC and return `403 Forbidden` for non-admin users.

### JWT signing key configuration

JWT signing uses:

- `JWT_SIGNING_KEY` (preferred)
- fallback: Django `SECRET_KEY` (development convenience)

See `docs/SETUP.md` for full details.

## JWT endpoints

JWT endpoints are mounted in `djecommerce/urls.py`:

- `POST /api/auth/token/` obtain access and refresh tokens
- `POST /api/auth/token/refresh/` refresh an access token using a refresh token
- `POST /api/auth/token/verify/` verify a token’s signature/validity

A minimal JWT-protected identity endpoint is also exposed:

- `GET /api/auth/me/` (JWT required)

> Note: There is also an API identity endpoint mounted under the `core` app:
>
> - `GET /api/me/`
>
> Both `/api/auth/me/` and `/api/me/` return basic user identity data and require authentication. The `/api/auth/me/` route is used as the “JWT wiring” smoke test in this documentation.

### Obtain tokens

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"pass12345"}'
```

Response contains:

- `access` (short-lived access token)
- `refresh` (longer-lived refresh token)

### Use the access token

```bash
curl -s http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

If the header is missing or invalid, the API returns `401`.

### Refresh the access token

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/refresh/ \
  -H 'Content-Type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
```

### Verify a token

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/token/verify/ \
  -H 'Content-Type: application/json' \
  -d '{"token":"<access_or_refresh_token>"}'
```

## RBAC (role-based access control)

### How RBAC is represented

RBAC is implemented as a lightweight “Admin role” concept.

A user is treated as an admin if any of the following is true:

- user is a Django superuser
- user is marked `is_staff`
- user is a member of the Django group named `Admin`

This logic is enforced for API endpoints using the DRF permission class:

- `core.api_permissions.IsAdminRole`

Admin-only template views use a separate gate:

- `core.rbac.request_is_admin` (used by `user_passes_test`)

### Bootstrap RBAC

Run:

```bash
python manage.py setup_rbac
```

This command ensures the `Admin` group exists and grants it model-level permissions for:

- `Item`
- `Order`

The permission grants correspond to add/change/delete/view for each model. Admin-only APIs are additionally protected at the endpoint layer by `IsAdminRole`.

### Admin-only routes

Admin-only API routes include (not exhaustive, but core surfaces):

- `/api/admin/**` (admin APIs)
- `/api/admin/products/**` (product management APIs)

Admin-only template routes include:

- `/manage/**` (operations/management pages)
  - `/manage/orders/`
  - `/manage/orders/<order_id>/transition/`

## RBAC examples (403 vs success)

### Example: admin API denied (403)

1) Get a token for a normal user:

```bash
ACCESS=$(curl -s -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"normal","password":"pass12345"}' | python -c "import sys,json; print(json.load(sys.stdin)['access'])")
```

2) Call an admin-only endpoint:

```bash
curl -i http://127.0.0.1:8000/api/admin/items/ \
  -H "Authorization: Bearer $ACCESS"
```

Expected result:

- `403 Forbidden`
- response body includes a message similar to: `Admin privileges are required to perform this action.`

### Example: admin API allowed (200)

Add the user to the `Admin` group (for example via Django admin UI), or via shell:

```python
# python manage.py shell
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()
u = User.objects.get(username="normal")
u.groups.add(Group.objects.get(name="Admin"))
```

Then obtain a fresh token and call again:

```bash
curl -i http://127.0.0.1:8000/api/admin/items/ \
  -H "Authorization: Bearer <admin_access_token>"
```

Expected result:

- `200 OK`
- JSON list of items

## Notes on CSRF

- Session-based template forms rely on CSRF and must include `{% csrf_token %}`; these routes are protected by Django’s CSRF middleware.
- The Stripe webhook endpoint is explicitly marked `@csrf_exempt` because it is called by Stripe, not a browser.
- JWT-based API calls do not use CSRF as the primary protection mechanism; they require the `Authorization: Bearer <token>` header.

## Token lifetime defaults

The SimpleJWT configuration in `djecommerce/settings/base.py` uses:

- access token lifetime: 5 minutes
- refresh token lifetime: 7 days
- refresh rotation enabled

These are reasonable defaults for reducing the impact of access token leakage while maintaining usability for API clients.
