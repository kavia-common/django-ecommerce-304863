"""
Initialize Flasky (the sibling Flask app mounted at /flask) database.

This unified runtime mounts Django at `/` and Flasky at `/flask` via combined_wsgi.py.
Flasky is a legacy Flask-SQLAlchemy app that (in this repository layout) lives at:
    <monorepo-root>/flasky-304863

This script:
- Ensures Flasky's sqlite DB schema exists (db.create_all()).
- Seeds minimal data required for common pages to render without missing-table errors:
  - inserts roles (Role.insert_roles())
  - inserts a default user and one sample post (optional but helps index page)

Run (from django-ecommerce-304863/):
    python scripts/init_flasky_db.py

Environment variables:
- FLASK_CONFIG (optional): Flasky config name. Defaults to "default" (development).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# PUBLIC_INTERFACE
def init_flasky_db() -> None:
    """Create Flasky DB tables and seed minimal data (roles + a user + one post)."""
    monorepo_root = Path(__file__).resolve().parents[2]
    flasky_repo_dir = monorepo_root / "flasky-304863"

    if not flasky_repo_dir.exists():
        raise FileNotFoundError(
            f"Expected Flasky repo at '{flasky_repo_dir}', but it was not found."
        )

    # Ensure `import app` resolves to flasky-304863/app
    if str(flasky_repo_dir) not in sys.path:
        sys.path.insert(0, str(flasky_repo_dir))

    from app import create_app, db  # type: ignore
    from app.models import Post, Role, User  # type: ignore

    config_name = os.environ.get("FLASK_CONFIG", "default")
    app = create_app(config_name)

    with app.app_context():
        # Create all tables (Flasky does not ship Flask-Migrate in this template)
        db.create_all()

        # Seed roles used by permissions checks
        Role.insert_roles()

        # Create a minimal user and post so the index has something to render.
        user = User.query.filter_by(email="smoke@example.com").first()
        if user is None:
            user = User(email="smoke@example.com", username="smoke")
            user.password = "smoke"
            db.session.add(user)
            db.session.commit()

        if Post.query.count() == 0:
            post = Post(body="Smoke test post", author=user)
            db.session.add(post)
            db.session.commit()

        # Trivial connectivity verification
        _ = Role.query.count()
        _ = User.query.count()
        _ = Post.query.count()


if __name__ == "__main__":
    init_flasky_db()
    print("Flasky DB initialized OK")
