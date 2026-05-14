"""Lockfile reader auto-detection (filename + content sniff)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

FILENAME_TO_READER = {
    "uv.lock": "uv_lock",
    "poetry.lock": "poetry_lock",
    "Pipfile.lock": "pipfile_lock",
    "package-lock.json": "package_lock_json",
    "pnpm-lock.yaml": "pnpm_lock_yaml",
    "pnpm-lock.yml": "pnpm_lock_yaml",
}

FILENAME_PATTERNS = [
    (re.compile(r"^requirements.*\.txt$"), "requirements_txt"),
]

_RE_REQUIREMENTS_LINE = re.compile(r"^[\w.\-\[\]]+==[\w.\-+]+")


def detect_reader(path: Path) -> Optional[str]:
    name = path.name
    if name in FILENAME_TO_READER:
        return FILENAME_TO_READER[name]
    for pattern, reader in FILENAME_PATTERNS:
        if pattern.match(name):
            return reader

    try:
        head = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    stripped = head.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(head)
        except Exception:
            return None
        if isinstance(data, dict):
            if "_meta" in data:
                return "pipfile_lock"
            if "lockfileVersion" in data:
                return "package_lock_json"
        return None

    if re.search(r"^\[metadata\]", head, re.MULTILINE) and \
            re.search(r"^lock-version\s*=", head, re.MULTILINE):
        return "poetry_lock"
    if re.search(r"^\[\[package\]\]", head, re.MULTILINE):
        return "uv_lock"
    if re.search(r"^lockfileVersion\s*:", head, re.MULTILINE):
        return "pnpm_lock_yaml"

    for line in head.splitlines():
        if _RE_REQUIREMENTS_LINE.match(line.strip()):
            return "requirements_txt"

    return None


__all__ = ["detect_reader", "FILENAME_TO_READER", "FILENAME_PATTERNS"]
