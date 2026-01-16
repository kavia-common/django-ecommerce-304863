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
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


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


STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WriteResult:
    """Result of a file write attempt."""

    path: Path
    changed: bool
    old_sha256: Optional[str]
    new_sha256: str


class Logger:
    """Simple structured logger with UTC timestamps and optional verbosity."""

    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose

    def _ts(self) -> str:
        return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _emit(self, level: str, msg: str) -> None:
        print(f"[auto_reconcile {self._ts()}] {level}: {msg}", flush=True)

    def info(self, msg: str) -> None:
        self._emit("INFO", msg)

    def warn(self, msg: str) -> None:
        self._emit("WARN", msg)

    def error(self, msg: str) -> None:
        self._emit("ERROR", msg)

    def debug(self, msg: str) -> None:
        if self._verbose:
            self._emit("DEBUG", msg)


@dataclass(frozen=True)
class Config:
    """Runtime configuration for a reconciliation run."""

    repo_root: Path = REPO_ROOT
    autogen_dir: Path = AUTOGEN_DIR
    state_path: Path = STATE_PATH

    flasky_remote_url: str = FLASKY_REMOTE_URL

    requirements_path: Path = REQUIREMENTS_PATH
    env_example_path: Path = ENV_EXAMPLE_PATH

    dockerfile_path: Path = DOCKERFILE_PATH
    compose_candidates: Tuple[Path, ...] = tuple(COMPOSE_CANDIDATES)

    # Loop cadence
    interval_seconds: int = 300

    # Behavior toggles
    dry_run: bool = False
    verbose: bool = False

    # Retry knobs (kept small to preserve current "best-effort" behavior)
    git_ls_remote_retries: int = 2
    git_ls_remote_timeout_s: int = 30


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_cmd(
    args: Sequence[str], cwd: Optional[Path] = None, timeout_s: int = 30
) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    p = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
        text=True,
    )
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def _git_available() -> bool:
    rc, _, _ = _run_cmd(["git", "--version"], timeout_s=10)
    return rc == 0


def _read_text(path: Path) -> str:
    """Read UTF-8 text from a path."""
    return path.read_text(encoding="utf-8")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """
    Atomically write bytes to `path` by writing to a temp file in the same directory then replacing.

    This ensures readers never see a partially-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(path.parent), prefix=f".{path.name}.tmp."
    ) as tf:
        tmp_name = tf.name
        tf.write(content)
        tf.flush()
        os.fsync(tf.fileno())
    os.replace(tmp_name, path)


def _write_text_if_changed(path: Path, content: str, *, dry_run: bool) -> WriteResult:
    """
    Write `content` to `path` only if the bytes differ from the existing file.

    Performs an atomic update when changes are necessary.

    Returns:
        WriteResult describing whether a change occurred.
    """
    new_bytes = content.encode("utf-8")
    new_sha = _sha256_bytes(new_bytes)

    if path.exists():
        old_bytes = path.read_bytes()
        old_sha = _sha256_bytes(old_bytes)
        if old_sha == new_sha:
            return WriteResult(
                path=path, changed=False, old_sha256=old_sha, new_sha256=new_sha
            )
    else:
        old_sha = None

    if not dry_run:
        _atomic_write_bytes(path, new_bytes)
    return WriteResult(path=path, changed=True, old_sha256=old_sha, new_sha256=new_sha)


def _compute_change_summary(repo_root: Path, writes: List[WriteResult]) -> dict:
    changed = [w for w in writes if w.changed]
    return {
        "files_touched": [str(w.path.relative_to(repo_root)) for w in writes],
        "files_changed": [str(w.path.relative_to(repo_root)) for w in changed],
        "changed_count": len(changed),
    }


def _get_local_git_head(repo_root: Path, logger: Logger) -> Optional[str]:
    """Return local repo HEAD sha if available, else None."""
    if not _git_available() or not (repo_root / ".git").exists():
        logger.debug("git not available or .git missing; local HEAD unavailable")
        return None
    rc, out, err = _run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, timeout_s=10)
    if rc != 0:
        logger.warn(f"unable to read local git HEAD: {err or out}")
        return None
    return out


def _get_flasky_remote_head(config: Config, logger: Logger) -> Optional[str]:
    """
    Get Flasky HEAD commit sha without cloning/vendoring.

    Uses `git ls-remote <url> HEAD` which fetches remote refs metadata only.
    Best-effort with small retries to mitigate transient network issues.
    """
    if not _git_available():
        logger.debug("git not available; Flasky remote HEAD unavailable")
        return None

    last_err: str = ""
    for attempt in range(1, config.git_ls_remote_retries + 2):
        rc, out, err = _run_cmd(
            ["git", "ls-remote", config.flasky_remote_url, "HEAD"],
            timeout_s=config.git_ls_remote_timeout_s,
        )
        if rc == 0:
            # Output format: "<sha>\tHEAD"
            m = re.match(r"^([0-9a-f]{40})\s+HEAD$", out)
            if m:
                return m.group(1)
            logger.warn(f"unexpected ls-remote output; cannot parse HEAD: {out!r}")
            return None

        last_err = err or out
        logger.warn(
            f"unable to query Flasky remote refs (attempt {attempt}): {last_err}"
        )
        # brief backoff, but keep small to preserve prior behavior (fast loop)
        if attempt < config.git_ls_remote_retries + 1:
            time.sleep(min(1.0 * attempt, 3.0))

    logger.warn(f"giving up querying Flasky remote refs: {last_err}")
    return None


def _merge_requirements(django_req_text: str) -> str:
    """
    Reconcile requirements.txt.

    Policy for this project/task:
    - Prefer newest compatible versions; ties favor Django.
    - We do not vendor Flasky requirements, we only use Flasky metadata to annotate state.
    - For now, we keep Django's pinned set as authoritative and do not add Flask pins
      automatically (because "newest compatible" requires dependency resolution tooling).

    Current behavior: normalize line endings and ensure a trailing newline.
    """
    return "\n".join(django_req_text.splitlines()).rstrip() + "\n"


def _regenerate_env_example(env_example_text: str) -> str:
    """
    Regenerate `.env.example`.

    Current behavior: keep existing file content as authoritative and normalize formatting.
    """
    return "\n".join(env_example_text.splitlines()).rstrip() + "\n"


class StateStore:
    """Loads/saves schema-versioned state in `.autogen/state.json` with basic migration."""

    def __init__(
        self, state_path: Path, repo_root: Path, logger: Logger, *, dry_run: bool
    ) -> None:
        self._state_path = state_path
        self._repo_root = repo_root
        self._logger = logger
        self._dry_run = dry_run

    def load(self) -> dict:
        """Load state from disk. On corruption, returns a minimal state marker but does not raise."""
        if not self._state_path.exists():
            return {}

        try:
            raw = json.loads(_read_text(self._state_path))
        except Exception:
            # Preserve prior behavior: don't fail reconciliation due to corrupted state.
            self._logger.warn(
                "state.json is corrupted/unreadable; will be overwritten on next save"
            )
            return {"_corrupted": True, "schema_version": STATE_SCHEMA_VERSION}

        if not isinstance(raw, dict):
            self._logger.warn(
                "state.json is not an object; will be overwritten on next save"
            )
            return {"_corrupted": True, "schema_version": STATE_SCHEMA_VERSION}

        migrated = self._migrate_if_needed(raw)
        return migrated

    def save(self, state: Mapping[str, Any]) -> None:
        """Persist state atomically (unless dry-run)."""
        data = dict(state)
        if "schema_version" not in data:
            data["schema_version"] = STATE_SCHEMA_VERSION

        serialized = json.dumps(data, indent=2, sort_keys=True) + "\n"
        if self._dry_run:
            self._logger.info("DRY-RUN: would update .autogen/state.json")
            return
        _atomic_write_bytes(self._state_path, serialized.encode("utf-8"))

    def _migrate_if_needed(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate older schema versions to current.

        Current schema_version is 1. If missing, assume 0 and migrate to 1.
        """
        version = state.get("schema_version")
        if version is None:
            # v0 -> v1: add schema_version, keep the rest as-is.
            self._logger.debug("migrating state schema_version: <missing> -> 1")
            migrated = dict(state)
            migrated["schema_version"] = 1
            return migrated

        if isinstance(version, int) and version == STATE_SCHEMA_VERSION:
            return state

        # Future-proofing: if newer version encountered, keep it but don't break.
        if isinstance(version, int) and version > STATE_SCHEMA_VERSION:
            self._logger.warn(
                f"state.json schema_version={version} is newer than supported ({STATE_SCHEMA_VERSION}); "
                "continuing without migration"
            )
            return state

        # Unknown/unsupported older schema: mark, but keep contents.
        self._logger.warn(
            f"state.json schema_version={version!r} is unsupported; continuing best-effort"
        )
        migrated = dict(state)
        migrated["schema_version"] = STATE_SCHEMA_VERSION
        migrated["_migrated_from"] = version
        return migrated


class Reconciler:
    """Orchestrates a single reconciliation cycle."""

    def __init__(self, config: Config, logger: Logger) -> None:
        self._config = config
        self._logger = logger
        self._state_store = StateStore(
            config.state_path, config.repo_root, logger, dry_run=config.dry_run
        )

    def run_once(self) -> int:
        """
        Run a single reconcile cycle.

        Returns:
            Exit code (0 success, non-zero on fatal error).
        """
        self._logger.info("Starting reconcile cycle")
        state_before = self._state_store.load()

        local_head = _get_local_git_head(self._config.repo_root, self._logger)
        flasky_head = _get_flasky_remote_head(self._config, self._logger)

        writes: List[WriteResult] = []

        # Requirements reconciliation
        try:
            if self._config.requirements_path.exists():
                req_text = _read_text(self._config.requirements_path)
                new_req = _merge_requirements(req_text)
                writes.append(
                    _write_text_if_changed(
                        self._config.requirements_path,
                        new_req,
                        dry_run=self._config.dry_run,
                    )
                )
            else:
                self._logger.warn("requirements.txt not found; skipping")
        except Exception as e:
            # Treat manifest IO as fatal: these are local files and should be reliable.
            self._logger.error(f"failed to reconcile requirements.txt: {e!r}")
            return 1

        # .env.example regeneration
        try:
            if self._config.env_example_path.exists():
                env_text = _read_text(self._config.env_example_path)
                new_env = _regenerate_env_example(env_text)
                writes.append(
                    _write_text_if_changed(
                        self._config.env_example_path,
                        new_env,
                        dry_run=self._config.dry_run,
                    )
                )
            else:
                self._logger.warn(".env.example not found; skipping")
        except Exception as e:
            self._logger.error(f"failed to reconcile .env.example: {e!r}")
            return 1

        # Docker/compose manifests (regenerate only if present; we do not create new infra files here)
        if self._config.dockerfile_path.exists():
            self._logger.info(
                "NOTE: Dockerfile present but regeneration is not implemented; leaving unchanged"
            )
        for p in self._config.compose_candidates:
            if p.exists():
                self._logger.info(
                    f"NOTE: compose file present ({p.name}) but regeneration is not implemented; leaving unchanged"
                )

        change_summary = _compute_change_summary(self._config.repo_root, writes)

        state_after: Dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "last_run_utc": _utc_now_iso(),
            "flasky": {
                "remote_url": self._config.flasky_remote_url,
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
                "dry_run": bool(self._config.dry_run),
            }
        )
        state_after["history"] = history[-20:]

        # Saving state is best-effort, but local IO should work; treat as fatal if it fails.
        try:
            self._state_store.save(state_after)
        except Exception as e:
            self._logger.error(f"failed to write state.json: {e!r}")
            return 1

        for w in writes:
            if w.changed:
                if self._config.dry_run:
                    self._logger.info(
                        f"DRY-RUN: would update {w.path.relative_to(self._config.repo_root)}"
                    )
                else:
                    self._logger.info(
                        f"UPDATED: {w.path.relative_to(self._config.repo_root)}"
                    )
            else:
                self._logger.info(
                    f"OK(no change): {w.path.relative_to(self._config.repo_root)}"
                )

        self._logger.info(
            f"Cycle complete: changed_count={change_summary['changed_count']}, "
            f"flasky_head={flasky_head or 'unknown'}"
        )
        return 0


def _interruptible_sleep(seconds: int, logger: Logger) -> None:
    """
    Sleep for `seconds` in small increments so Ctrl+C interrupts promptly.
    """
    remaining = max(0, int(seconds))
    while remaining > 0:
        time.sleep(min(1, remaining))
        remaining -= 1
        logger.debug(f"sleeping... remaining={remaining}s")


# PUBLIC_INTERFACE
def run_once() -> int:
    """
    Run a single reconcile cycle with default configuration.

    Returns:
        Exit code (0 success, non-zero on fatal error).
    """
    config = Config()
    logger = Logger(verbose=False)
    return Reconciler(config=config, logger=logger).run_once()


# PUBLIC_INTERFACE
def run_loop(interval_seconds: int = 300) -> int:
    """
    Run reconcile cycles forever, sleeping `interval_seconds` between cycles.

    Args:
        interval_seconds: Sleep duration between cycles (default: 300 seconds).

    Returns:
        Exit code (non-zero only on immediate fatal argument/config error).
    """
    # Preserve prior guardrail.
    if interval_seconds < 5:
        Logger(verbose=False).error(
            "Refusing to run with interval_seconds < 5 (too tight)."
        )
        return 2

    config = Config(interval_seconds=interval_seconds)
    logger = Logger(verbose=False)
    reconciler = Reconciler(config=config, logger=logger)

    logger.info(f"Starting reconcile loop (interval_seconds={interval_seconds})")
    while True:
        try:
            reconciler.run_once()
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt; exiting loop")
            return 0
        except Exception as e:
            # Preserve prior loop resilience: never crash the loop; log and continue.
            logger.error(f"cycle failed with exception: {e!r}")

        try:
            _interruptible_sleep(interval_seconds, logger)
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt during sleep; exiting loop")
            return 0


def _cmd_status(config: Config, logger: Logger) -> int:
    state_store = StateStore(
        config.state_path, config.repo_root, logger, dry_run=config.dry_run
    )
    state = state_store.load()
    if not state:
        print("No state found. Run `python scripts/auto_reconcile.py run` first.")
        return 0
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entrypoint.

    Preserves existing subcommands and flags:
      - run
      - loop --interval-seconds
      - status

    Adds backward-compatible flags:
      --dry-run     Preview changes without writing files.
      --verbose     More detailed logs.
    """
    parser = argparse.ArgumentParser(
        description="Auto-reconcile Django repo with Flasky metadata every 5 minutes."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing any files.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable verbose debug logging."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="Run a single reconcile cycle.")

    p_loop = sub.add_parser("loop", help="Run reconcile cycles forever.")
    p_loop.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Sleep interval between cycles (default: 300).",
    )

    sub.add_parser("status", help="Print the last saved state.json.")

    args = parser.parse_args(argv)

    config = Config(
        interval_seconds=int(getattr(args, "interval_seconds", 300)),
        dry_run=bool(args.dry_run),
        verbose=bool(args.verbose),
    )
    logger = Logger(verbose=config.verbose)
    reconciler = Reconciler(config=config, logger=logger)

    if args.cmd == "run":
        return reconciler.run_once()
    if args.cmd == "loop":
        return run_loop(interval_seconds=int(args.interval_seconds))
    if args.cmd == "status":
        return _cmd_status(config, logger)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
