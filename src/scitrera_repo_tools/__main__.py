"""Dispatcher for `python -m scitrera_repo_tools <subcommand>`."""

from __future__ import annotations

import sys


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: repo-tools <subcommand> [options]\n"
            "\n"
            "subcommands:\n"
            "  sync-versions    Synchronize versions across a monorepo from versions.yaml\n"
        )
        sys.exit(0 if argv else 1)

    subcommand = argv[0]
    remaining = argv[1:]

    if subcommand == "sync-versions":
        from scitrera_repo_tools.version_sync.cli import main as sync_main
        sys.argv = ["sync-versions", *remaining]
        sync_main()
    else:
        print(f"unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
