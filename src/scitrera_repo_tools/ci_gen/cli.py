"""CLI entrypoint for `generate-ci`."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..version_sync.cli import _find_config
from ..version_sync.config import ConfigError, load_config
from .runner import run

logger = logging.getLogger("scitrera_repo_tools.ci_gen")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-ci",
        description=(
            "Generate GitHub Actions workflows from versions.yaml. Without "
            "flags: creates missing files and emits a unified diff for any "
            "files that drift from the generator output (exit 1 on drift). "
            "Use --force to overwrite drift, --check to never write."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing workflow files that differ from the generator.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Never write; exit 1 if any file is missing or drifted.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to versions.yaml (default: search upward from cwd).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Monorepo root (default: parent directory of the config file).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Workflows directory (default: <root>/.github/workflows).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.force and args.check:
        logger.error("--force and --check are mutually exclusive.")
        sys.exit(2)

    if args.config is not None:
        yaml_path = args.config.resolve()
        if not yaml_path.is_file():
            logger.error("Config file not found: %s", yaml_path)
            sys.exit(2)
    else:
        found = _find_config(Path.cwd())
        if found is None:
            logger.error(
                "No versions.yaml found in cwd or any parent directory. "
                "Pass --config <path> explicitly."
            )
            sys.exit(2)
        yaml_path = found

    root: Optional[Path] = None
    if args.root is not None:
        root = args.root.resolve()
        if not root.is_dir():
            logger.error("Root directory does not exist: %s", root)
            sys.exit(2)

    try:
        config = load_config(yaml_path, root=root)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    workflows_dir = (
        args.output.resolve()
        if args.output is not None
        else config.root / ".github" / "workflows"
    )

    sys.exit(
        run(
            config,
            workflows_dir=workflows_dir,
            force=args.force,
            check_only=args.check,
        )
    )


__all__ = ["main"]
