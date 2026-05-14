"""uv.lock reader (TOML with [[package]] blocks)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Dict


def read(path: Path) -> Dict[str, str]:
    with path.open("rb") as f:
        data = tomllib.load(f)

    packages = data.get("package", [])
    out: Dict[str, str] = {}
    if isinstance(packages, list):
        for entry in packages:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            ver = entry.get("version")
            if isinstance(name, str) and isinstance(ver, str):
                out[name] = ver
    return out


__all__ = ["read"]
