"""go.mod require-line strategy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import _make_gomod_re, _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def update_gomod_require(
    path: Path,
    version: str,
    dry_run: bool,
    target_module: str,
) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    pattern = _make_gomod_re(target_module)
    m = pattern.search(text)
    if not m:
        logger.warning(
            "No require line for %s found in %s", target_module, path
        )
        return False, None

    old = m.group(2)
    if old == version:
        return False, old

    new_text = pattern.sub(rf"\g<1>{version}", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, old


def rewrite_gomod_require(
    path: Path,
    dep_name: str,
    new_requirement: str,
    dry_run: bool,
    *,
    resolve_local_refs: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Rewrite an existing `require <dep_name> v<version>` line in go.mod.

    `dep_name` is the Go module path (e.g., `google.golang.org/grpc`).
    `new_requirement` is the target version, with or without leading `v`
    (e.g., `v1.65.0` or `1.65.0`).

    `resolve_local_refs` has no effect on Go: `replace` directives don't
    affect downstream consumers (Go 1.21+) and are not rewritten.

    Returns (changed, old_version_with_v_prefix).
    """
    del resolve_local_refs  # accepted for signature parity; see docstring
    bare = new_requirement[1:] if new_requirement.startswith("v") else new_requirement

    text = _read_text(path)
    pattern = _make_gomod_re(dep_name)
    m = pattern.search(text)
    if m is None:
        return False, None

    old_bare = m.group(2)
    if old_bare == bare:
        return False, f"v{old_bare}"

    new_text = pattern.sub(rf"\g<1>{bare}", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, f"v{old_bare}"


__all__ = ["update_gomod_require", "rewrite_gomod_require"]
