"""pnpm-lock.yaml reader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import yaml


def _split_name_version(key: str) -> "tuple[str, str] | None":
    # Format: '<name>@<version>' or '/<name>@<version>' (older pnpm).
    s = key.lstrip("/")
    # Find the last '@' that begins a version (digit follows).
    m = re.search(r"@([^@/(]+)$", s)
    if not m:
        return None
    name = s[: m.start()]
    version = m.group(1)
    # Strip suffix like '_react@18' or '(react@18)'.
    version = version.split("_", 1)[0].split("(", 1)[0]
    if not name or not version:
        return None
    return name, version


def read(path: Path) -> Dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    if not isinstance(data, dict):
        return out

    packages = data.get("packages")
    if isinstance(packages, dict):
        for key in packages.keys():
            if not isinstance(key, str):
                continue
            parsed = _split_name_version(key)
            if parsed:
                name, version = parsed
                out.setdefault(name, version)

    snapshots = data.get("snapshots")
    if isinstance(snapshots, dict):
        for key in snapshots.keys():
            if not isinstance(key, str):
                continue
            parsed = _split_name_version(key)
            if parsed:
                name, version = parsed
                out.setdefault(name, version)

    return out


__all__ = ["read"]
