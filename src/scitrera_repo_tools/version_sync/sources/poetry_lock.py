"""poetry.lock reader (TOML, same [[package]] shape as uv but with [metadata])."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .uv_lock import read as _read_uv_style


def read(path: Path) -> Dict[str, str]:
    return _read_uv_style(path)


__all__ = ["read"]
