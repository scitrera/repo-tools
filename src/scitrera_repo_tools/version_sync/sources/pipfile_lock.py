"""Pipfile.lock reader (JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

_OPERATOR_PREFIXES = (">=", "<=", "==", "~=", "!=", ">", "<")


def _strip_operator(spec: str) -> str:
    s = spec.strip()
    for prefix in _OPERATOR_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix):].strip()
    return s


def read(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for section in ("default", "develop"):
        block = data.get(section, {})
        if not isinstance(block, dict):
            continue
        for name, info in block.items():
            if not isinstance(info, dict):
                continue
            spec = info.get("version")
            if isinstance(spec, str):
                out[name] = _strip_operator(spec)
    return out


__all__ = ["read"]
