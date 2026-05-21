"""CLI entrypoint for `npm-audit`."""

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
from .runner import AUDIT_LEVELS, run

logger = logging.getLogger("scitrera_repo_tools.npm_audit")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npm-audit",
        description=(
            "Run `npm audit` (and optionally `npm audit fix`) across every "
            "TypeScript package declared in versions.yaml."
        ),
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Run `npm audit fix` before the audit reporting step.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass `--force` to `npm audit fix` (breaking changes). Requires --fix.",
    )
    parser.add_argument(
        "--level",
        choices=AUDIT_LEVELS,
        default=None,
        help="Only report vulnerabilities at this severity or higher.",
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
        help="Monorepo root for resolving relative paths "
             "(default: parent directory of the config file).",
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project names from versions.yaml to audit (default: all TS projects).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

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

    sys.exit(
        run(
            config,
            selected=args.projects or None,
            fix=args.fix,
            force=args.force,
            level=args.level,
        )
    )


__all__ = ["main"]
