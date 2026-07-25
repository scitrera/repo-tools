"""CLI entrypoint for `sync-versions`."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, load_config
from .runner import run

logger = logging.getLogger("scitrera_repo_tools.version_sync")

DEFAULT_CONFIG_NAMES = ("versions.yaml", "versions.yml")


def _find_config(start: Path) -> Optional[Path]:
    cur = start.resolve()
    while True:
        for name in DEFAULT_CONFIG_NAMES:
            candidate = cur / name
            if candidate.is_file():
                return candidate
        if cur.parent == cur:
            return None
        cur = cur.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-versions",
        description="Synchronize subproject versions from versions.yaml",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: report drift and exit 1 if any change is needed",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show every file inspected, not just changes",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to versions.yaml (default: search upward from cwd)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Monorepo root for resolving relative paths "
             "(default: parent directory of the config file)",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help=(
            "Release-prep mode: also rewrite local-reference dep specifiers "
            "(`file:`, `workspace:`, `link:`, git/url, PEP 508 `@ git+...`) "
            "into the canonical version from versions.yaml. Use this BEFORE "
            "publishing to PyPI/npm; default behavior preserves local refs."
        ),
    )
    parser.add_argument(
        "--print-version",
        metavar="PROJECT",
        default=None,
        help=(
            "Print the version of PROJECT from versions.yaml to stdout and "
            "exit. Useful for CI workflows that need to tag artifacts with "
            "a project's authoritative version. Exits 2 if PROJECT is "
            "unknown. Suppresses normal sync output."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

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

    if args.print_version is not None:
        version = config.project_versions.get(args.print_version)
        if version is None:
            logger.error(
                "Unknown project '%s' in versions.yaml. Known projects: %s",
                args.print_version,
                ", ".join(sorted(config.project_versions)) or "(none)",
            )
            sys.exit(2)
        print(version)
        sys.exit(0)

    sys.exit(
        run(config, check=args.check, verbose=args.verbose, release=args.release)
    )


__all__ = ["main"]
