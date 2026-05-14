"""package-lock.json reader (npm; supports lockfileVersion 1, 2, 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def read(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}

    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, info in packages.items():
            if not key or not isinstance(info, dict):
                continue
            name = info.get("name")
            if not isinstance(name, str):
                if key.startswith("node_modules/"):
                    name = key[len("node_modules/"):]
                else:
                    continue
            ver = info.get("version")
            if isinstance(ver, str):
                out.setdefault(name, ver)

    deps = data.get("dependencies")
    if isinstance(deps, dict):
        for name, info in deps.items():
            if not isinstance(info, dict):
                continue
            ver = info.get("version")
            if isinstance(ver, str):
                out.setdefault(name, ver)

    return out


__all__ = ["read"]
