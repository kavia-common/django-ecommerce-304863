"""
Implementation of staged deployment steps for the unified Django+Flask runtime.

Stages:
- django50: deps + collectstatic + migrate + warmup / ; then PAUSE checkpoint
- flask: deps + best-effort init Flasky DB + warmup /flask + /flask/health ; then PAUSE checkpoint
- finalize: warmup both + graceful gunicorn reload (SIGHUP) ; then mark finalized

This module does NOT start/stop Gunicorn and does NOT modify runtime entrypoints.
"""

from __future__ import annotations

import os
import signal
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from scripts.deploy_state import update_state

REPO_ROOT = Path(__file__).resolve().parents[1]


class DeployError(RuntimeError):
    """Raised for staged deployment failures that should stop the workflow."""


def _log(msg: str) -> None:
    print(msg, flush=True)


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


def _run(
    args: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    check: bool = True,
) -> ExecResult:
    p = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    res = ExecResult(p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip())
    if check and res.returncode != 0:
        raise DeployError(
            f"Command failed rc={res.returncode}: {' '.join(args)}\n"
            f"stdout:\n{res.stdout}\n\nstderr:\n{res.stderr}\n"
        )
    return res


def _venv_paths() -> Tuple[Path, Path]:
    venv_dir = Path(os.environ.get("VENV_PATH", str(REPO_ROOT / "venv"))).resolve()
    python_exe = venv_dir / "bin" / "python"
    return venv_dir, python_exe


def ensure_venv_and_deps() -> None:
    """Ensure venv exists and requirements are installed (idempotent)."""
    venv_dir, python_exe = _venv_paths()
    if not python_exe.exists():
        _log(f"[deploy] creating venv at {venv_dir}")
        _run(["python3", "-m", "venv", str(venv_dir)], cwd=REPO_ROOT)

    _log("[deploy] installing deps from requirements.txt")
    _run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], cwd=REPO_ROOT)
    _run(
        [str(python_exe), "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=REPO_ROOT,
    )


def _django_manage(args: Sequence[str]) -> None:
    _, python_exe = _venv_paths()
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "djecommerce.settings.development")
    _run([str(python_exe), "manage.py", *list(args)], cwd=REPO_ROOT, env=env)


def _http_get(url: str, *, timeout_s: int = 5) -> Tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec B310
            body = resp.read(512).decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        body = (e.read(512) or b"").decode("utf-8", errors="replace")
        return int(e.code), body
    except Exception as e:
        raise DeployError(f"Warmup request failed for {url}: {e!r}") from e


def _base_url() -> str:
    host = os.environ.get("HOST", "127.0.0.1")
    port = os.environ.get("PORT", "8000")
    return f"http://{host}:{port}"


def warmup(paths: Sequence[str]) -> None:
    base = _base_url().rstrip("/")
    for p in paths:
        url = base + p
        _log(f"[deploy] warmup GET {url}")
        code, body = _http_get(url)
        if code >= 500:
            raise DeployError(f"Warmup failed {code} for {url}. Body: {body!r}")


def _try_init_flasky_db() -> None:
    script = REPO_ROOT / "scripts" / "init_flasky_db.py"
    if not script.exists():
        _log("[deploy] init_flasky_db.py missing; skipping Flasky DB init")
        return
    _, python_exe = _venv_paths()
    try:
        _log("[deploy] initializing Flasky DB (best-effort)")
        _run([str(python_exe), str(script)], cwd=REPO_ROOT, check=True)
    except DeployError as e:
        _log(f"[deploy] WARN: Flasky DB init failed (continuing): {e}")


def _discover_gunicorn_pid() -> Optional[int]:
    env_pid = os.environ.get("GUNICORN_PID")
    if env_pid and env_pid.isdigit():
        return int(env_pid)

    pidfile_candidates = [
        REPO_ROOT / ".autogen" / "gunicorn.pid",
        REPO_ROOT / "gunicorn.pid",
        Path("/tmp/gunicorn.pid"),
    ]
    for p in pidfile_candidates:
        if p.exists():
            txt = p.read_text(encoding="utf-8").strip()
            if txt.isdigit():
                return int(txt)

    try:
        res = _run(
            ["pgrep", "-f", "gunicorn combined_wsgi:application"],
            cwd=REPO_ROOT,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            first = res.stdout.splitlines()[0].strip()
            if first.isdigit():
                return int(first)
    except Exception:
        return None

    return None


def graceful_reload() -> None:
    """Send SIGHUP to Gunicorn master PID if discoverable."""
    pid = _discover_gunicorn_pid()
    if not pid:
        _log("[deploy] gunicorn PID not discovered; skipping SIGHUP reload")
        return
    _log(f"[deploy] sending SIGHUP to gunicorn master pid={pid}")
    try:
        os.kill(pid, signal.SIGHUP)
    except ProcessLookupError:
        _log("[deploy] WARN: PID not found; skipping reload")
    except PermissionError as e:
        raise DeployError(
            f"Permission denied sending SIGHUP to pid {pid}: {e!r}"
        ) from e


# PUBLIC_INTERFACE
def stage_django50() -> None:
    """Django Stage 1: deps + collectstatic + migrate + warmup then PAUSE checkpoint."""
    _log("[deploy] stage=django50")
    ensure_venv_and_deps()
    _django_manage(["collectstatic", "--noinput"])
    _django_manage(["migrate", "--noinput"])
    warmup(["/"])
    update_state(
        {
            "paused": True,
            "current_context": "django",
            "checkpoint": "django50_complete",
        }
    )
    _log("[deploy] PAUSED (django50_complete)")


# PUBLIC_INTERFACE
def stage_flask() -> None:
    """Flask Stage 2: deps + best-effort DB init + warmup then PAUSE checkpoint."""
    _log("[deploy] stage=flask")
    ensure_venv_and_deps()
    _try_init_flasky_db()
    warmup(["/flask", "/flask/health"])
    update_state(
        {
            "paused": True,
            "current_context": "flask",
            "checkpoint": "flask_complete",
        }
    )
    _log("[deploy] PAUSED (flask_complete)")


# PUBLIC_INTERFACE
def stage_finalize() -> None:
    """Finalize: warmup both mounts + graceful gunicorn reload; mark finalized."""
    _log("[deploy] stage=finalize")
    warmup(["/", "/flask/health"])
    graceful_reload()
    update_state(
        {
            "paused": False,
            "current_context": "finalize",
            "checkpoint": "finalized",
        }
    )
    _log("[deploy] FINALIZED")
