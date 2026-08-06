"""Go version-declaration strategy: `const Version` and `var version`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import (
    _RE_GO_VERSION_ANY,
    _RE_GO_VERSION_CONST,
    _read_text,
    _write_text,
)

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def _select_pattern(text: str):
    """`const Version` wins wherever it appears; otherwise accept the broader form.

    Both forms are rewritten with `count=1`, so in a file declaring each of them
    the choice of pattern decides which line moves. `const Version` was the only
    form this rule ever matched, so preferring it means upgrading repo-tools
    cannot silently retarget an existing rule onto a different declaration —
    the broader pattern only ever applies where the old one found nothing.
    """
    if _RE_GO_VERSION_CONST.search(text):
        return _RE_GO_VERSION_CONST
    return _RE_GO_VERSION_ANY


def update_go_version(path: Path, version: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    pattern = _select_pattern(text)
    m = pattern.search(text)
    if not m:
        logger.warning(
            "No `const Version = \"...\"` or `var version = \"...\"` found in %s", path
        )
        return False, None

    old = text[m.start(1) + len(m.group(1)):m.end(2) - len(m.group(2))]
    if old == version:
        return False, old

    new_text = pattern.sub(rf"\g<1>{version}\2", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, old


__all__ = ["update_go_version"]
