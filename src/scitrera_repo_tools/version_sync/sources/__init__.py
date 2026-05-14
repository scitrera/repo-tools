"""Lockfile source readers (auto-detected by filename + content)."""

from __future__ import annotations

from typing import Callable, Dict

from . import (
    package_lock_json,
    pipfile_lock,
    pnpm_lock_yaml,
    poetry_lock,
    requirements_txt,
    uv_lock,
)
from .detect import detect_reader

SOURCE_READER_MAP: Dict[str, Callable] = {
    "uv_lock": uv_lock.read,
    "poetry_lock": poetry_lock.read,
    "requirements_txt": requirements_txt.read,
    "pipfile_lock": pipfile_lock.read,
    "package_lock_json": package_lock_json.read,
    "pnpm_lock_yaml": pnpm_lock_yaml.read,
}

__all__ = ["SOURCE_READER_MAP", "detect_reader"]
