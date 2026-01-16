# Flasky DB initialization (unified runtime)

This repo runs a **unified Gunicorn** process via:

- `django-ecommerce-304863/combined_wsgi.py`
  - Django at `/`
  - Flasky (sibling repo `flasky-304863`) at `/flask`

Flasky is a legacy Flask-SQLAlchemy app that **does not use Alembic/Flask-Migrate** in this template, so DB schema must be created using `db.create_all()`.

## Initialize Flasky DB

From `django-ecommerce-304863/`:

```bash
python scripts/init_flasky_db.py
```

This will:

- create tables (`db.create_all()`)
- seed roles (`Role.insert_roles()`)
- create one user + one post (helps `/flask/` index render)

Optionally set config:

```bash
export FLASK_CONFIG=default
python scripts/init_flasky_db.py
```

## Smoke-tested endpoints (via combined runtime)

After DB init, start the server:

```bash
./scripts/start_combined_gunicorn.sh
```

Then validate:

- `GET /flask` (in this repo, this is currently a lightweight health response `ok\n`)
- `GET /flask/health` (200 `ok\n`)
- `GET /flask/auth/login` (200 HTML)
- `GET /flask/auth/register` (200 HTML)
- `GET /flask/api/v1/posts/` (401 JSON "unauthorized" is acceptable; confirms route is working and not 500)
