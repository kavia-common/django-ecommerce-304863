# Runtime (single container)

This container is started via `.project_manifest.yaml` and intentionally **ignores any Dockerfiles** in the repo.

Startup uses a single Gunicorn process running `combined_wsgi:application`:
- Django served at `/`
- Flasky (Flask app) served at `/flask`

Entrypoint script:
- `scripts/start_combined_gunicorn.sh`

Port:
- Always binds to `0.0.0.0:8000` (the manifest exports `PORT=8000`).
