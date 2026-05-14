"""requirements*.txt / pip-freeze reader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

_RE_NAME = re.compile(r"^([A-Za-z0-9_.\-]+)")


def read(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        # Drop environment markers (everything after ';').
        line = line.split(";", 1)[0].strip()
        name_part, _, version_part = line.partition("==")
        name_match = _RE_NAME.match(name_part.strip())
        if not name_match:
            continue
        name = name_match.group(1)
        # Strip trailing whitespace/comma-separated extra specifiers.
        version = version_part.strip().split(",", 1)[0].strip()
        if not version:
            continue
        out[name] = version
    return out


__all__ = ["read"]
