# ADR-001: JWT Authentication for APIs and RBAC for Admin Surfaces

## Overview

This decision record documents the choice to add JWT authentication for API endpoints while preserving session-based authentication for template-rendered pages, and to enforce a simple RBAC policy for administrative routes.

## Context

The codebase is a legacy Django 2.2 e-commerce application originally built around server-rendered templates and session authentication (`django-allauth`). New requirements introduced:

- API access for programmatic clients
- Admin-only API endpoints for product management, inventory, and order operations
- A clear authorization boundary between normal users and administrative users

At the same time, the existing template flows needed to remain functional and unchanged.

## Decision

### JWT for `/api/**` endpoints

The project uses:

- Django REST Framework for API views
- SimpleJWT for token issuance and verification

DRF is configured to use JWT authentication and to require authentication by default for API routes. JWT endpoints are mounted under `/api/auth/*`.

A minimal protected identity endpoint (`/api/auth/me/`) exists as a wiring and smoke-test route for deployments.

### Sessions for template routes

Existing template routes remain session-based and use `django-allauth` under `/accounts/`.

This preserves:
- CSRF protection for browser forms
- minimal disruption to the existing UI and flows

### RBAC for admin surfaces

Admin access is granted if the user is any of:

- `is_superuser`
- `is_staff`
- a member of the Django group named `Admin`

RBAC is enforced by:

- `core.api_permissions.IsAdminRole` on admin-only API routes (e.g. `/api/admin/**`, `/api/admin/products/**`)
- `user_passes_test` on admin-only template routes under `/manage/**`

A management command (`python manage.py setup_rbac`) ensures the `Admin` group exists and has model-level permissions for `Item` and `Order`.

## Consequences

- API clients must manage Bearer tokens (access/refresh), and token lifetime/rotation policies apply.
- Template views continue to depend on sessions and CSRF; API views are intentionally not designed for cookie-based auth in this repository.
- Admin-only protection is centralized and consistent across both API and template management routes.
- Production deployments should set a dedicated `JWT_SIGNING_KEY` to allow JWT rotation independent of `SECRET_KEY`.

## Notes

This ADR reflects the current repository state:

- JWT configuration is in `djecommerce/settings/base.py`.
- JWT routes are in `djecommerce/urls.py`.
- RBAC setup command is `core/management/commands/setup_rbac.py`.
- Admin role logic is expressed in `core/api_permissions.py` and `core/rbac.py`.
