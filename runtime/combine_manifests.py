"""
Runtime manifest combiner.

This container runs a *single* unified Gunicorn process (combined_wsgi.py), but we
want to retain per-repo runtime metadata/settings as separate manifests and
combine them at runtime into one effective manifest for discovery/metadata.

Merge rules:
- Dicts are merged recursively.
- Lists are concatenated (de-duplicated for simple scalar lists).
- On scalar conflicts, the first manifest (Django) wins.
- Keys explicitly namespaced (containing "__") are treated as independent and
  are never overridden by non-namespaced keys.
"""

from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List


def _is_namespaced_key(key: str) -> bool:
    """Return True if a key is explicitly namespaced (e.g. FLASKY__FOO)."""
    return "__" in key


def _dedupe_scalars(items: List[Any]) -> List[Any]:
    """Dedupe scalar list items while preserving order."""
    out: List[Any] = []
    seen = set()
    for x in items:
        if isinstance(x, (str, int, float, bool)) or x is None:
            if x in seen:
                continue
            seen.add(x)
        out.append(x)
    return out


def _merge(a: Any, b: Any) -> Any:
    """
    Merge b into a (without mutating inputs) and return merged result.

    Django-first behavior is implemented by calling _merge(django, flasky) such that
    on conflicts, values in `a` are kept.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        result: Dict[str, Any] = deepcopy(a)
        for k, v in b.items():
            if k not in result:
                result[k] = deepcopy(v)
                continue

            # If key is explicitly namespaced, never let it be overridden by non-namespaced,
            # but since "a wins", we still preserve existing; for completeness, if existing
            # is non-namespaced and incoming is namespaced, we keep both by storing incoming
            # under its exact key (already the case) — this branch is only reached when same key.
            if _is_namespaced_key(k) and not _is_namespaced_key(k):
                # Unreachable given same key; keep for clarity.
                result[k] = deepcopy(result[k])
                continue

            result[k] = _merge(result[k], v)
        return result

    if isinstance(a, list) and isinstance(b, list):
        combined = deepcopy(a) + deepcopy(b)
        return _dedupe_scalars(combined)

    # Scalar conflict: keep a (Django wins)
    return deepcopy(a)


def _read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON file and return dict."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a JSON object at top-level: {path}")
    return data


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write dict to JSON file (pretty) ensuring parent exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


# PUBLIC_INTERFACE
def combine_manifests(
    django_manifest_path: str,
    flasky_manifest_path: str,
    out_path: str,
) -> str:
    """
    Combine per-repo manifests into a single effective manifest.

    Args:
        django_manifest_path: Path to Django manifest JSON.
        flasky_manifest_path: Path to Flasky manifest JSON.
        out_path: Output path for the combined manifest JSON.

    Returns:
        The output path (string) where the combined manifest was written.
    """
    dj_path = Path(django_manifest_path).resolve()
    fl_path = Path(flasky_manifest_path).resolve()
    out = Path(out_path).resolve()

    django = _read_json(dj_path)
    flasky = _read_json(fl_path)

    combined: Dict[str, Any] = {
        "manifest_version": 1,
        "combined_from": [
            {"path": str(dj_path), "repo": django.get("repo", {}).get("name", "django")},
            {"path": str(fl_path), "repo": flasky.get("repo", {}).get("name", "flasky")},
        ],
        "effective": _merge(django, flasky),
    }

    # Stamp minimal runtime metadata for downstream discovery/inspection.
    combined["effective"].setdefault("runtime", {})
    combined["effective"]["runtime"].setdefault("entrypoint", {})
    combined["effective"]["runtime"]["entrypoint"].setdefault(
        "combined_manifest_path", str(out)
    )

    _write_json(out, combined)
    return str(out)


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Combine per-repo runtime manifests.")
    parser.add_argument(
        "--django",
        default=os.environ.get(
            "DJANGO_RUNTIME_MANIFEST",
            "runtime/manifests/django.runtime_manifest.json",
        ),
        help="Path to Django runtime manifest JSON.",
    )
    parser.add_argument(
        "--flasky",
        default=os.environ.get(
            "FLASKY_RUNTIME_MANIFEST",
            "runtime/manifests/flasky.runtime_manifest.json",
        ),
        help="Path to Flasky runtime manifest JSON.",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get(
            "COMBINED_RUNTIME_MANIFEST",
            "runtime/combined.runtime_manifest.json",
        ),
        help="Path to output combined runtime manifest JSON.",
    )

    args = parser.parse_args()
    combine_manifests(args.django, args.flasky, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
