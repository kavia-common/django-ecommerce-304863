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

# Run Gunicorn serving combined WSGI:
# - Django mounted at /
# - Flask mounted at /flask
exec gunicorn combined_wsgi:application \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --access-logfile - \
  --error-logfile -
