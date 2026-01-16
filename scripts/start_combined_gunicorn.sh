#!/usr/bin/env sh
set -eu

# This script is intentionally Dockerfile-agnostic; it is invoked by .project_manifest.yaml
# and serves as the single runtime entrypoint for the combined Django+Flask WSGI app.

# Ensure we're running from the container root (repo root for this container)
cd "$(dirname "$0")/.."

# If a venv exists (as created by manifest build/install), activate it.
if [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "venv/bin/activate"
fi

# Force bind to port 8000 regardless of PreviewManager placeholder port.
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Default workers can be overridden with WEB_CONCURRENCY
WORKERS="${WEB_CONCURRENCY:-2}"

# ---- Runtime manifest combiner (metadata/discovery only) ----
# Generate an effective combined manifest at startup without altering the actual
# runtime process model (still one Gunicorn serving combined_wsgi).
#
# The combined manifest is intended for discovery/metadata tools and future
# runtime introspection; it does not affect routing/ports (Django at /, Flask at /flask).
DJANGO_RUNTIME_MANIFEST="${DJANGO_RUNTIME_MANIFEST:-runtime/manifests/django.runtime_manifest.json}"
FLASKY_RUNTIME_MANIFEST="${FLASKY_RUNTIME_MANIFEST:-runtime/manifests/flasky.runtime_manifest.json}"
COMBINED_RUNTIME_MANIFEST="${COMBINED_RUNTIME_MANIFEST:-runtime/combined.runtime_manifest.json}"
export COMBINED_RUNTIME_MANIFEST

python -m runtime.combine_manifests \
  --django "${DJANGO_RUNTIME_MANIFEST}" \
  --flasky "${FLASKY_RUNTIME_MANIFEST}" \
  --out "${COMBINED_RUNTIME_MANIFEST}"

# Run Gunicorn serving combined WSGI:
# - Django mounted at /
# - Flask mounted at /flask
exec gunicorn combined_wsgi:application \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --access-logfile - \
  --error-logfile -
