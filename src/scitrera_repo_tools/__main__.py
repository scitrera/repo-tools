"""Dispatcher for `python -m scitrera_repo_tools <subcommand>`."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

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
            "  npm-audit        Run `npm audit` across every TS package in versions.yaml\n"
            "  missing-deps     Print pyproject.toml deps that are not yet installed\n"
            "  directory-split  Split a directory into N approximately-equal buckets\n"
            "  generate-ci-gha      Generate GitHub Actions workflows from versions.yaml\n"
            "  compile-protos       Compile .proto files per the versions.yaml proto block\n"
        )
        sys.exit(0 if argv else 1)

    subcommand = argv[0]
    remaining = argv[1:]

    if subcommand == "sync-versions":
        from scitrera_repo_tools.version_sync.cli import main as sync_main
        sys.argv = ["sync-versions", *remaining]
        sync_main()
    elif subcommand == "npm-audit":
        from scitrera_repo_tools.npm_audit.cli import main as audit_main
        sys.argv = ["npm-audit", *remaining]
        audit_main()
    elif subcommand == "missing-deps":
        from scitrera_repo_tools.missing_deps import main as missing_deps_main
        sys.argv = ["missing-deps", *remaining]
        sys.exit(missing_deps_main())
    elif subcommand == "directory-split":
        from scitrera_repo_tools.directory_split import main as dir_split_main
        sys.exit(dir_split_main(remaining))
    elif subcommand == "generate-ci-gha":
        from scitrera_repo_tools.ci_gen_gha.cli import main as ci_main
        sys.argv = ["generate-ci-gha", *remaining]
        ci_main()
    elif subcommand == "compile-protos":
        from scitrera_repo_tools.compile_protos.cli import main as protos_main
        sys.argv = ["compile-protos", *remaining]
        protos_main()
    else:
        print(f"unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
