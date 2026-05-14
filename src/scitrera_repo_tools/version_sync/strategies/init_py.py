"""__init__.py __version__ strategy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import _RE_INIT_VERSION, _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def update_init_py(path: Path, version: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    m = _RE_INIT_VERSION.search(text)
    if not m:
        logger.warning("No __version__ found in %s", path)
        return False, None

    old = text[m.start(1) + len(m.group(1)):m.end(2) - len(m.group(2))]
    if old == version:
        return False, old

    new_text = _RE_INIT_VERSION.sub(rf"\g<1>{version}\2", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, old


__all__ = ["update_init_py"]
