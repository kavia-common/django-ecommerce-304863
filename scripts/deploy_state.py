"""
Shared checkpoint state utilities for staged deployment.

State file:
  django-ecommerce-304863/.autogen/deploy/state.json

We keep this intentionally small and dependency-free.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOGEN_DEPLOY_DIR = REPO_ROOT / ".autogen" / "deploy"
STATE_PATH = AUTOGEN_DEPLOY_DIR / "state.json"


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# PUBLIC_INTERFACE
def load_state() -> Dict[str, Any]:
    """Load staged deploy state from disk (returns {} if absent/unreadable)."""
    if not STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


# PUBLIC_INTERFACE
def save_state(state: Dict[str, Any]) -> None:
    """Persist staged deploy state to disk using a simple atomic replace."""
    AUTOGEN_DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


# PUBLIC_INTERFACE
def update_state(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update (merge) state dict and persist.

    Args:
        patch: Keys to merge into existing state.

    Returns:
        Updated full state dict.
    """
    state = load_state()
    state.update(patch)
    state.setdefault("schema_version", 1)
    state["updated_at_utc"] = _utc_now_iso()
    save_state(state)
    return state
