# Dependency Update Summary

Date: 2026-01-17

## Key runtime pins (Django e-commerce)
- Django pinned to **5.2.10** (stay on Django 5.2 LTS line; patch-level stability/security updates).
- django-allauth pinned to **65.13.1** (compat with Django 5.x).
- stripe pinned to **14.1.0**.
- requests pinned to **2.32.3**; urllib3 pinned to **2.3.0**; certifi pinned to **2025.1.31**.
- gunicorn pinned to **23.0.0**.
- Pillow pinned to **12.1.0**.

## Notes / follow-ups
- This repo currently mixes dev tooling pins into `requirements.txt` (e.g., ruff/pylint/autopep8). Consider splitting into `requirements-dev.txt` in a follow-up.
- Legacy Flask app remains constrained to `Flask<3`, `Flask-SQLAlchemy<3`, `SQLAlchemy<2` to avoid breaking the `/flask` mounted runtime.
- `pip-tools` was not present in the environment, so no `pip-compile` lockfile update was performed.
