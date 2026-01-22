# Dependency Update Summary

Date: 2026-01-22

## Package manager / files
- Uses **pip** with `requirements.txt` and `requirements-dev.txt`.
- `pyproject.toml` is used for tooling config only (ruff/isort/black).

## Key runtime pins (Django e-commerce)
- Django pinned to **6.0.1** (tested import OK in this environment).
- django-allauth pinned to **65.14.0** (compatible with Django 6.0.x).
- stripe pinned to **14.2.0**.
- gunicorn pinned to **23.0.0**.
- Pillow pinned to **12.1.0**.
- django-countries pinned to **8.2.0**.
- django-crispy-forms pinned to **2.5** and crispy-bootstrap4 pinned to **2025.6**.

## HTTP stack pinning (conflict avoidance)
During upgrades, pip selected newer versions of `certifi`, `idna`, `requests`, `urllib3` that caused resolver warnings with other installed packages.
To keep this repo stable and avoid cross-package conflicts, the following are pinned (highest compatible set already used by this repo previously):
- requests==2.32.3
- urllib3==2.3.0
- certifi==2025.1.31
- idna==3.10

## Dev-only pins
- django-debug-toolbar pinned to **6.2.0**.
- ruff==0.14.13, pylint==4.0.4, autopep8==2.3.2, pycodestyle==2.14.0.

## Notes / follow-ups
- If you decide to remain on Django 5.2 LTS instead of Django 6.x, downgrade Django accordingly and re-run resolution; current pins were validated by imports only (no full test suite run).
- No migrations are expected solely from these package upgrades, but verify the auth/allauth flows and Stripe checkout in staging.
- Legacy Flask app remains constrained to `Flask<3`, `Flask-SQLAlchemy<3`, `SQLAlchemy<2` to avoid breaking the `/flask` mounted runtime.
