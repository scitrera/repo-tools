"""marketplace.json strategy (Claude Code marketplace registry)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def update_marketplace(
    path: Path,
    version: str,
    dry_run: bool,
    project_dir: str,
) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    data = json.loads(text)

    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        logger.warning("No 'plugins' array in %s", path)
        return False, None

    target = None
    for entry in plugins:
        source = entry.get("source", "") if isinstance(entry, dict) else ""
        if project_dir in source:
            target = entry
            break

    if target is None:
        logger.warning(
            "No plugin with source containing '%s' in %s", project_dir, path,
        )
        return False, None

    old = target.get("version")
    if old == version:
        return False, old

    target["version"] = version

    if not dry_run:
        _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True, old


__all__ = ["update_marketplace"]
