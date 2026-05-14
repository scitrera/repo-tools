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


__all__ = ["update_gomod_require"]
