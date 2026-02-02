# Django E-commerce (docs)

## Overview

This `docs/` folder contains the developer and operational documentation for the Django e-commerce application in this repository. The project is a legacy Django 2.2 codebase that has been updated with an API layer using Django REST Framework and JWT (SimpleJWT) while continuing to support classic Django template views with session authentication.

## Quickstart (local)

1. Create and activate a virtual environment.
2. Install dependencies from `requirements.txt`.
3. Create a `.env` file (see `docs/SETUP.md` for all variables).
4. Run migrations and RBAC bootstrap:

   - `python manage.py migrate`
   - `python manage.py setup_rbac`

5. Start the dev server:

   - `python manage.py runserver`

6. Smoke checks

   - Open `http://127.0.0.1:8000/` to confirm the storefront loads.
   - Obtain a JWT: `POST http://127.0.0.1:8000/api/auth/token/`
   - Call the JWT-protected identity endpoint: `GET http://127.0.0.1:8000/api/auth/me/`

## Where to go next

- Local setup and environment variables: `docs/SETUP.md`
- Authentication and RBAC (sessions vs JWT, admin-only routes): `docs/AUTH_AND_RBAC.md`
- Feature guide + API endpoint catalog: `docs/FEATURES_AND_APIS.md`
- Deployment and operational runbooks: `docs/OPERATIONS_RUNBOOK.md`
- Decision record (JWT + RBAC): `docs/ADR-001-jwt-rbac.md`
