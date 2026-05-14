"""package.json strategy: version field + dependency rewrite helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")

_DEP_KEYS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)

# npm/pnpm/yarn dep specifiers that are NOT version requirements; rewriting
# these would break local workspace dev or git/url-based installs.
_NON_VERSION_PREFIXES = (
    "file:",
    "link:",
    "workspace:",
    "git+",
    "git://",
    "github:",
    "gitlab:",
    "bitbucket:",
    "http://",
    "https://",
    "npm:",
    "./",
    "../",
)


def _is_non_version_spec(spec: str) -> bool:
    return spec.startswith(_NON_VERSION_PREFIXES)


def update_json_version(path: Path, version: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    data = json.loads(text)
    old = data.get("version")
    if old == version:
        return False, old

    data["version"] = version

    if not dry_run:
        _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True, old


def rewrite_package_json_dep(
    path: Path,
    dep_name: str,
    new_requirement: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    data = json.loads(text)

    changed = False
    old_spec: Optional[str] = None
    for key in _DEP_KEYS:
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        if dep_name in section:
            existing = section[dep_name]
            if existing == new_requirement:
                continue
            if isinstance(existing, str) and _is_non_version_spec(existing):
                # Preserve workspace/file/git/url specifiers; pre-publish tooling
                # is expected to convert these to version specifiers at release time.
                continue
            if old_spec is None:
                old_spec = existing
            section[dep_name] = new_requirement
            changed = True

    if not changed:
        return False, None

    if not dry_run:
        _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True, old_spec


__all__ = ["update_json_version", "rewrite_package_json_dep"]
