#!/usr/bin/env python3
"""
Auto-reconcile script for django-ecommerce-304863.

This script is designed to be safe in preview environments:
- It NEVER starts/stops servers or containers.
- It ONLY reads/writes files inside this repository and logs actions.
- It is idempotent: re-running will not rewrite files if content is unchanged.

Every run:
1) Analyzes the local Django repository and the remote Flasky repo metadata
   (https://github.com/miguelgrinberg/flasky) without vendoring the repo.
2) Regenerates selected "manifests" (currently requirements.txt and .env.example)
   and applies them to this repository.
3) Persists a small state file at .autogen/state.json with last run details.

Usage:
    python scripts/auto_reconcile.py run
    python scripts/auto_reconcile.py loop --interval-seconds 300
    python scripts/auto_reconcile.py status
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

FLASKY_REMOTE_URL = "https://github.com/miguelgrinberg/flasky"

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOGEN_DIR = REPO_ROOT / ".autogen"
STATE_PATH = AUTOGEN_DIR / "state.json"

REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

# Files we might regenerate if present in this repo (currently none exist).
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
COMPOSE_CANDIDATES = [
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.yaml",
    REPO_ROOT / "compose.yml",
    REPO_ROOT / "compose.yaml",
    REPO_ROOT / "docker-compose.preview.yml",
    REPO_ROOT / "docker-compose.preview.yaml",
]


@dataclass(frozen=True)
class WriteResult:
    """Result of a file write attempt."""

    path: Path
    changed: bool
    old_sha256: Optional[str]
    new_sha256: str


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text_if_changed(path: Path, content: str) -> WriteResult:
    """
    Write `content` to `path` only if the bytes differ from the existing file.

    Returns a WriteResult describing whether a change occurred.
    """
    new_bytes = content.encode("utf-8")
    new_sha = _sha256_bytes(new_bytes)

    if path.exists():
        old_bytes = path.read_bytes()
        old_sha = _sha256_bytes(old_bytes)
        if old_sha == new_sha:
            return WriteResult(path=path, changed=False, old_sha256=old_sha, new_sha256=new_sha)
    else:
        old_sha = None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return WriteResult(path=path, changed=True, old_sha256=old_sha, new_sha256=new_sha)


def _log(msg: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[auto_reconcile {ts}] {msg}", flush=True)


def _run_cmd(args: List[str], cwd: Path | None = None, timeout_s: int = 30) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    p = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
        text=True,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _git_available() -> bool:
    rc, _, _ = _run_cmd(["git", "--version"], timeout_s=10)
    return rc == 0


def _get_local_git_head() -> Optional[str]:
    """Return local repo HEAD sha if available, else None."""
    if not _git_available() or not (REPO_ROOT / ".git").exists():
        return None
    rc, out, _ = _run_cmd(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, timeout_s=10)
    return out if rc == 0 else None


def _get_flasky_remote_head() -> Optional[str]:
    """
    Get Flasky HEAD commit sha without cloning/vendoring.

    Uses `git ls-remote <url> HEAD` which fetches remote refs metadata only.
    """
    if not _git_available():
        return None
    rc, out, err = _run_cmd(["git", "ls-remote", FLASKY_REMOTE_URL, "HEAD"], timeout_s=30)
    if rc != 0:
        _log(f"WARNING: unable to query Flasky remote refs: {err or out}")
        return None
    # Output format: "<sha>\tHEAD"
    m = re.match(r"^([0-9a-f]{40})\s+HEAD$", out)
    return m.group(1) if m else None


def _parse_requirements_pins(requirements_text: str) -> Dict[str, str]:
    """
    Parse `pkg==version` pins from a requirements.txt style file.

    Ignores comments, blank lines, and non-pinned requirements.
    """
    pins: Dict[str, str] = {}
    for raw in requirements_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Basic pin parser: name==version
        if "==" in line and "@" not in line:
            name, ver = line.split("==", 1)
            name = name.strip()
            ver = ver.strip()
            if name and ver:
                pins[name] = ver
    return pins


def _merge_requirements(django_req_text: str) -> str:
    """
    Reconcile requirements.txt.

    Policy for this project/task:
    - Prefer newest compatible versions; ties favor Django.
    - We do not vendor Flasky requirements, we only use Flasky metadata to annotate state.
    - For now, we keep Django's pinned set as authoritative and do not add Flask pins
      automatically (because "newest compatible" requires dependency resolution tooling).
    """
    # Current implementation: keep as-is but normalize line endings and ensure trailing newline.
    # This makes the loop safe and idempotent while still persisting Flasky commit metadata.
    normalized = "\n".join(django_req_text.splitlines()).rstrip() + "\n"
    return normalized


def _regenerate_env_example(env_example_text: str) -> str:
    """
    Regenerate `.env.example`.

    Currently keeps the existing file content as authoritative and normalizes formatting.
    """
    normalized = "\n".join(env_example_text.splitlines()).rstrip() + "\n"
    return normalized


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(_read_text(STATE_PATH))
    except Exception:
        # If corrupted, don't fail reconciliation; overwrite on next save.
        return {"_corrupted": True}


def _save_state(state: dict) -> None:
    AUTOGEN_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compute_change_summary(writes: List[WriteResult]) -> dict:
    changed = [w for w in writes if w.changed]
    return {
        "files_touched": [str(w.path.relative_to(REPO_ROOT)) for w in writes],
        "files_changed": [str(w.path.relative_to(REPO_ROOT)) for w in changed],
        "changed_count": len(changed),
    }


# PUBLIC_INTERFACE
def run_once() -> int:
    """
    Run a single reconcile cycle.

    Returns:
        Exit code (0 success, non-zero on fatal error).
    """
    _log("Starting reconcile cycle")
    state_before = _load_state()

    local_head = _get_local_git_head()
    flasky_head = _get_flasky_remote_head()

    writes: List[WriteResult] = []

    # Requirements reconciliation
    if REQUIREMENTS_PATH.exists():
        req_text = _read_text(REQUIREMENTS_PATH)
        new_req = _merge_requirements(req_text)
        writes.append(_write_text_if_changed(REQUIREMENTS_PATH, new_req))
    else:
        _log("WARNING: requirements.txt not found; skipping")

    # .env.example regeneration
    if ENV_EXAMPLE_PATH.exists():
        env_text = _read_text(ENV_EXAMPLE_PATH)
        new_env = _regenerate_env_example(env_text)
        writes.append(_write_text_if_changed(ENV_EXAMPLE_PATH, new_env))
    else:
        _log("WARNING: .env.example not found; skipping")

    # Docker/compose manifests (regenerate only if present; we do not create new infra files here)
    if DOCKERFILE_PATH.exists():
        _log("NOTE: Dockerfile present but regeneration is not implemented; leaving unchanged")
    for p in COMPOSE_CANDIDATES:
        if p.exists():
            _log(f"NOTE: compose file present ({p.name}) but regeneration is not implemented; leaving unchanged")

    change_summary = _compute_change_summary(writes)

    state_after = {
        "last_run_utc": _utc_now_iso(),
        "flasky": {
            "remote_url": FLASKY_REMOTE_URL,
            "head": flasky_head,
        },
        "django_repo": {
            "local_head": local_head,
        },
        "applied_changes": change_summary,
        "notes": [
            "This loop fetches Flasky remote metadata (HEAD sha) without cloning.",
            "Requirements/env regeneration is currently normalization + idempotent write; version reconciliation requires a resolver.",
        ],
    }

    # Keep a minimal history of last few runs to aid debugging.
    history = state_before.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "ran_at_utc": state_after["last_run_utc"],
            "changed_count": change_summary["changed_count"],
            "flasky_head": flasky_head,
        }
    )
    state_after["history"] = history[-20:]

    _save_state(state_after)

    for w in writes:
        if w.changed:
            _log(f"UPDATED: {w.path.relative_to(REPO_ROOT)}")
        else:
            _log(f"OK(no change): {w.path.relative_to(REPO_ROOT)}")

    _log(
        f"Cycle complete: changed_count={change_summary['changed_count']}, "
        f"flasky_head={flasky_head or 'unknown'}"
    )
    return 0


# PUBLIC_INTERFACE
def run_loop(interval_seconds: int = 300) -> int:
    """
    Run reconcile cycles forever, sleeping `interval_seconds` between cycles.

    Args:
        interval_seconds: Sleep duration between cycles (default: 300 seconds).

    Returns:
        Exit code (non-zero only on immediate fatal argument/config error).
    """
    if interval_seconds < 5:
        _log("Refusing to run with interval_seconds < 5 (too tight).")
        return 2

    _log(f"Starting reconcile loop (interval_seconds={interval_seconds})")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            _log("Received KeyboardInterrupt; exiting loop")
            return 0
        except Exception as e:
            # Never crash the loop in preview environments; log and continue.
            _log(f"ERROR: cycle failed with exception: {e!r}")
        time.sleep(interval_seconds)


def _cmd_status() -> int:
    state = _load_state()
    if not state:
        print("No state found. Run `python scripts/auto_reconcile.py run` first.")
        return 0
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-reconcile Django repo with Flasky metadata every 5 minutes.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="Run a single reconcile cycle.")

    p_loop = sub.add_parser("loop", help="Run reconcile cycles forever.")
    p_loop.add_argument("--interval-seconds", type=int, default=300, help="Sleep interval between cycles (default: 300).")

    sub.add_parser("status", help="Print the last saved state.json.")

    args = parser.parse_args(argv)

    if args.cmd == "run":
        return run_once()
    if args.cmd == "loop":
        return run_loop(interval_seconds=int(args.interval_seconds))
    if args.cmd == "status":
        return _cmd_status()

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
