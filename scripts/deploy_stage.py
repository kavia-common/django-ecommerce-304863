#!/usr/bin/env python3
"""
CLI shim for manifest-driven staged deployment.

This wrapper exists so the manifest can invoke:
  python scripts/deploy_stage.py --stage=django50
  python scripts/deploy_stage.py --stage=flask
  python scripts/deploy_stage.py --stage=finalize

Actual logic is implemented in scripts/deploy_impl.py.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from scripts.deploy_impl import stage_django50, stage_finalize, stage_flask


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Checkpoint-based staged deployment (django50 -> flask -> finalize)."
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=["django50", "flask", "finalize"],
        help="Which stage to run.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint."""
    args = _parse_args(argv)
    if args.stage == "django50":
        stage_django50()
        return 0
    if args.stage == "flask":
        stage_flask()
        return 0
    if args.stage == "finalize":
        stage_finalize()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
