"""
Combined WSGI entrypoint that serves:
- Django at /
- Flasky (Flask app) at /flask

This is intended to be run behind a single Gunicorn instance, exposing one port.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from django.core.wsgi import get_wsgi_application
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response


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


def _load_flasky_wsgi():
    """
    Load Flasky as a WSGI app.

    We do NOT vendor/copy Flasky into this project; instead we import it from a
    sibling directory `../flasky-304863` (present in this monorepo workspace).
    """
    flasky_repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "flasky-304863"))
    if flasky_repo_dir not in sys.path:
        sys.path.insert(0, flasky_repo_dir)

    # Flasky uses an app factory in app/__init__.py and typically config via FLASK_CONFIG.
    # Default config is 'default' per flasky config.py.
    from app import create_app  # type: ignore

    config_name = os.environ.get("FLASK_CONFIG", "default")
    return create_app(config_name)


# Django settings: prefer explicit DJANGO_SETTINGS_MODULE, but keep existing behavior
# consistent with manage.py defaults by falling back to development settings.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djecommerce.settings.development")

django_app = get_wsgi_application()

try:
    flasky_app = _load_flasky_wsgi()
except Exception as exc:
    # Keep the combined container healthy even if Flasky deps/env are missing.
    flasky_app = _make_placeholder_flask_app(exc)

# Mount Flasky under /flask; Django remains the default at /
application = DispatcherMiddleware(django_app, {"/flask": flasky_app})
