# Runtime (single container)

This container is started via `.project_manifest.yaml` and intentionally **ignores any Dockerfiles** in the repo.

Startup uses a single Gunicorn process running `combined_wsgi:application`:
- Django served at `/`
- Flasky (Flask app) served at `/flask`

Entrypoint script:
- `scripts/start_combined_gunicorn.sh`

Runtime manifest metadata:
- Per-repo manifests live under `runtime/manifests/`
  - `django.runtime_manifest.json`
  - `flasky.runtime_manifest.json`
- At container startup, the entrypoint runs `python -m runtime.combine_manifests`
  to generate `runtime/combined.runtime_manifest.json`.
- This combined manifest is for discovery/metadata only; the runtime still starts
  a single Gunicorn serving `combined_wsgi:application` (Django at `/`, Flask at `/flask`).

Port:
- Always binds to `0.0.0.0:8000` (the manifest exports `PORT=8000`).
