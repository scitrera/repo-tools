"""plugin.json strategy (Claude Code plugin manifests)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def update_plugin(path: Path, version: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    data = json.loads(text)
    old = data.get("version")
    if old == version:
        return False, old

    data["version"] = version

    if not dry_run:
        _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True, old


__all__ = ["update_plugin"]
