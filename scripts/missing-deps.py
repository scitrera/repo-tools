#!/usr/bin/env python3
"""Drop-in shim for scitrera-repo-tools `missing-deps`.

Copy this file into any repo's `scripts/` directory (or run it from anywhere)
to print the `pyproject.toml` dependencies that are not yet installed in the
current Python environment. Handy for selective `pip install` invocations.

Resolution order:

  1. Package already importable in the current Python  ->  call directly
     (fast path; exact version is whatever the current env has installed).

  2. `uvx` (or `uv`) on PATH  ->  run via uvx with no persistent install.
     Set `REPO_TOOLS_SOURCE` to override the package source. Default:
     `git+https://github.com/scitrera/repo-tools.git`. Pin to a tag or
     PyPI version, e.g.:
         REPO_TOOLS_SOURCE='scitrera-repo-tools==0.1.7'

  3. Otherwise  ->  print install instructions and exit 1.

Usage:
    python scripts/missing-deps.py                       # report missing deps
    python scripts/missing-deps.py --extra test          # include `[test]` extra
    python scripts/missing-deps.py --ignore some-pkg     # skip a package
    python scripts/missing-deps.py --print-installed     # also log to stderr

All flags pass through to `missing-deps`.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import os
import shutil
import sys
from typing import List

DEFAULT_SOURCE = "git+https://github.com/scitrera/repo-tools.git"


def _try_uvx(args: List[str]) -> None:
    """Replace the current process with a uvx invocation.

    Returns only if neither uvx nor uv is on PATH.
    """
    uv = shutil.which("uvx") or shutil.which("uv")
    if uv is None:
        return
    source = os.environ.get("REPO_TOOLS_SOURCE", DEFAULT_SOURCE)
    name = os.path.basename(uv)
    if name == "uv":
        cmd = [uv, "tool", "run", "--from", source, "missing-deps", *args]
    else:
        cmd = [uv, "--from", source, "missing-deps", *args]
    os.execvp(cmd[0], cmd)  # never returns


def _try_import(args: List[str]) -> bool:
    try:
        from scitrera_repo_tools.missing_deps import main as deps_main
    except ImportError:
        return False
    sys.argv = ["missing-deps", *args]
    sys.exit(deps_main())


def main(argv: List[str]) -> int:
    _try_import(argv)  # never returns when package is importable
    _try_uvx(argv)     # never returns when uvx/uv is on PATH
    source = os.environ.get("REPO_TOOLS_SOURCE", DEFAULT_SOURCE)
    sys.stderr.write(
        "scitrera-repo-tools is not available.\n"
        "Install one of:\n"
        f"  uv tool install --from {source} scitrera-repo-tools\n"
        f"  pip install {source}\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
