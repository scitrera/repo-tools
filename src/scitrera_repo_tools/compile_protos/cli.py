"""CLI entrypoint for `compile-protos`."""

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

logger = logging.getLogger("scitrera_repo_tools.compile_protos")

_LANG_CHOICES = ("go", "python", "typescript")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compile-protos",
        description=(
            "Compile .proto files for every language configured in the `proto:` "
            "block of versions.yaml, after verifying the installed toolchain "
            "matches proto.toolchain. Without flags: regenerates and writes any "
            "file that is missing or out of date. With --check: writes nothing "
            "and exits 1 on drift."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Never write; exit 1 if any generated file is missing or out of date.",
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
        "--lang",
        action="append",
        choices=_LANG_CHOICES,
        default=None,
        metavar="LANG",
        help=(
            "Restrict to one output language; repeatable. "
            f"Choices: {', '.join(_LANG_CHOICES)}. Default: every configured language."
        ),
    )
    parser.add_argument(
        "--python",
        dest="python_exe",
        default=None,
        help=(
            "Interpreter used for grpc_tools.protoc and for resolving the "
            "grpcio-tools pin (default: the interpreter running this command). "
            "Point this at a project virtualenv when repo-tools is installed "
            "elsewhere."
        ),
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help=(
            "Bypass toolchain pin verification. Generated artifacts embed tool "
            "versions, so this will likely produce drift — use only when you "
            "know the pins are wrong."
        ),
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="Under --check, report drifted files without printing unified diffs.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show in-sync files and satisfied toolchain pins, not just problems.",
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

    sys.exit(
        run(
            config,
            check_only=args.check,
            python_exe=args.python_exe,
            languages=args.lang,
            skip_verify=args.skip_verify,
            show_diff=not args.no_diff,
            verbose=args.verbose,
        )
    )


__all__ = ["main"]
