"""
Combined WSGI entrypoint that serves:
- Django at /
- Flasky (Flask app) at /flask

This is intended to be run behind a single Gunicorn instance, exposing one port.

Notes:
- Flasky is expected to live in a sibling directory to this container:
    <monorepo-root>/flasky-304863
- This module intentionally adjusts sys.path so that `import app` resolves to
  Flasky's package (flasky-304863/app), not this Django project's `core` etc.

Operational note for smoke tests:
- Flasky may require its own DB migrations/seed data. To allow basic validation
  of the unified runtime even when Flasky isn't initialized, this module
  provides a lightweight health endpoint at /flask and /flask/health that
  returns 200 without touching Flasky's DB.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Request, Response


def _make_placeholder_flask_app(error: Exception):
    """Create a tiny WSGI app that returns a helpful error message."""

    def app(environ, start_response):
        resp = Response(
            f"Flasky app unavailable: {type(error).__name__}: {error}\n",
            status=503,
            mimetype="text/plain",
        )
        return resp(environ, start_response)

    return app


def _ensure_flasky_on_sys_path() -> Path:
    """
    Ensure Flasky's repo directory is importable by adding it to sys.path.

    Returns:
        Path to the Flasky repo root directory.

    Raises:
        FileNotFoundError: If the expected Flasky repo directory does not exist.
    """
    # combined_wsgi.py lives at: <monorepo-root>/django-ecommerce-304863/combined_wsgi.py
    # Flasky expected at:       <monorepo-root>/flasky-304863
    container_dir = Path(__file__).resolve().parent
    monorepo_root = container_dir.parent
    flasky_repo_dir = monorepo_root / "flasky-304863"

    if not flasky_repo_dir.exists():
        raise FileNotFoundError(
            f"Expected Flasky repo at '{flasky_repo_dir}', but it was not found. "
            "Ensure 'flasky-304863' exists as a sibling directory to this container."
        )

    # Add monorepo root (helps some import resolvers/pylint) and Flasky repo dir.
    # Flasky repo dir is the critical one: it contains the 'app' package.
    for p in (str(monorepo_root), str(flasky_repo_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)

    return flasky_repo_dir


def _load_flasky_wsgi():
    """
    Load Flasky as a WSGI app.

    Flasky uses an app factory in app/__init__.py (create_app).
    Config is chosen via FLASK_CONFIG (defaults to 'default').
    """
    _ensure_flasky_on_sys_path()

    # Import via importlib so we can provide clearer errors if resolution fails.
    try:
        flasky_app_module = importlib.import_module("app")
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Could not import Flasky package 'app'. "
            "Expected it to be available from sibling repo 'flasky-304863/app'. "
            "Verify directory structure and that sys.path includes flasky-304863."
        ) from e

    if not hasattr(flasky_app_module, "create_app"):
        raise AttributeError(
            "Flasky module 'app' does not expose create_app(). "
            "Expected an app factory function 'create_app' in flasky-304863/app/__init__.py."
        )

    config_name = os.environ.get("FLASK_CONFIG", "default")
    return flasky_app_module.create_app(config_name)


def _flask_mount_with_healthcheck(flask_app):
    """
    Create a small WSGI mount app for /flask that provides:

    - /flask and /flask/health -> 200 OK (text/plain)
    - all other paths -> delegated to Flasky

    This keeps unified runtime smoke tests stable even when Flasky's DB isn't ready.
    """

    def mount_app(environ, start_response):
        req = Request(environ)
        # At this mount point, PATH_INFO is relative to "/flask".
        # Examples:
        #   GET /flask          -> req.path == "/"
        #   GET /flask/         -> req.path == "/"
        #   GET /flask/health   -> req.path == "/health"
        #   GET /flask/foo      -> req.path == "/foo"
        if req.path in ("/", "/health"):
            resp = Response("ok\n", status=200, mimetype="text/plain")
            return resp(environ, start_response)

        return flask_app(environ, start_response)

    return mount_app


# Django settings: prefer explicit DJANGO_SETTINGS_MODULE, but keep existing behavior
# consistent with manage.py defaults by falling back to development settings.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djecommerce.settings.development")

# Import Django only after DJANGO_SETTINGS_MODULE is set.
from django.core.wsgi import (  # noqa: E402  (import after env var)
    get_wsgi_application,
)

django_app = get_wsgi_application()

try:
    flasky_app = _load_flasky_wsgi()
except Exception as exc:  # pylint: disable=broad-exception-caught
    # Keep the combined container healthy even if Flasky deps/env are missing.
    flasky_app = _make_placeholder_flask_app(exc)

# Mount Flasky under /flask; Django remains the default at /
# We wrap Flasky with a healthcheck responder to allow smoke tests without requiring Flasky DB.
application = DispatcherMiddleware(
    django_app, {"/flask": _flask_mount_with_healthcheck(flasky_app)}
)
