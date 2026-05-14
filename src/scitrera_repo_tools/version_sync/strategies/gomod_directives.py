"""go.mod top-level directive strategies: `go X.Y` and `toolchain goX.Y.Z`.

These are distinct from `require` lines and managed via the reserved
top-level `go_toolchain` section in versions.yaml. Both rewriters are
no-inject: a missing directive returns (False, None) and a warning is
logged so the user can decide whether to add it manually.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from .base import _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")

# Matches the `go X.Y[.Z]` directive at the start of a line.
# Module paths in `require` lines never appear at column 0, and `go` is the
# only directive whose keyword is the literal `go`.
_RE_GO_DIRECTIVE = re.compile(r"(^[ \t]*go[ \t]+)(\S+)", re.MULTILINE)

# Matches the `toolchain goX.Y.Z` directive (Go 1.21+).
_RE_TOOLCHAIN_DIRECTIVE = re.compile(r"(^[ \t]*toolchain[ \t]+go)(\S+)", re.MULTILINE)


def update_gomod_go_directive(
    path: Path,
    version: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    m = _RE_GO_DIRECTIVE.search(text)
    if m is None:
        logger.warning("No `go` directive found in %s", path)
        return False, None

    old = m.group(2)
    if old == version:
        return False, old

    new_text = _RE_GO_DIRECTIVE.sub(rf"\g<1>{version}", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, old


def update_gomod_toolchain_directive(
    path: Path,
    version: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    """Update the `toolchain goX.Y.Z` directive.

    `version` may be given with or without a leading `go` (we accept
    `1.25.10` or `go1.25.10`).
    """
    bare = version[2:] if version.startswith("go") else version

    text = _read_text(path)
    m = _RE_TOOLCHAIN_DIRECTIVE.search(text)
    if m is None:
        logger.warning("No `toolchain` directive found in %s", path)
        return False, None

    old = m.group(2)
    if old == bare:
        return False, f"go{old}"

    new_text = _RE_TOOLCHAIN_DIRECTIVE.sub(rf"\g<1>{bare}", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, f"go{old}"


__all__ = ["update_gomod_go_directive", "update_gomod_toolchain_directive"]
