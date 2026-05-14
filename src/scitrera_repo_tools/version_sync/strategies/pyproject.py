"""pyproject.toml strategy: version field + dependency rewrite helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from .base import _RE_PYPROJECT_VERSION, _read_text, _write_text

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def update_pyproject(path: Path, version: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    text = _read_text(path)
    m = _RE_PYPROJECT_VERSION.search(text)
    if not m:
        logger.warning("No version field found in %s", path)
        return False, None

    old = text[m.start(1) + len(m.group(1)):m.end(2) - len(m.group(2))]
    if old == version:
        return False, old

    new_text = _RE_PYPROJECT_VERSION.sub(rf"\g<1>{version}\2", text, count=1)
    if not dry_run:
        _write_text(path, new_text)
    return True, old


_OPERATOR_PREFIXES = (">=", "<=", "==", "~=", "!=", ">", "<", "^", "~")

# PEP 508 direct-reference deps (`pkg @ git+...`, `pkg @ file:///...`, `pkg @ https://...`)
# carry their version via the URL, not a version spec; rewriting them would
# silently break the install.
def _is_non_version_spec(existing: str) -> bool:
    stripped = existing.lstrip()
    return stripped.startswith("@")


def _make_pyproject_dep_re(dep_name: str) -> "re.Pattern[str]":
    # Matches a quoted PEP 508 dep string such as:
    #   "pkg>=1.0"  'pkg[extra]==2.0,<3'  "pkg ~= 1.2 ; python_version<'3.12'"
    # Capture groups:
    #   1: opening quote + dep name + optional [extras] + optional whitespace
    #   2: existing version spec (everything up to ';' or closing quote)
    #   3: trailing marker / closing quote portion
    escaped = re.escape(dep_name)
    return re.compile(
        rf'''(?P<q>["'])(?P<prefix>{escaped}(?:\[[^\]]*\])?\s*)'''
        rf'''(?P<spec>[^"';]*)'''
        rf'''(?P<tail>(?:;[^"']*)?)(?P=q)''',
    )


def rewrite_pyproject_dep(
    path: Path,
    dep_name: str,
    new_requirement: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    """Rewrite the version part of an existing dep entry in a pyproject.toml.

    Only updates existing matching entries. Never inserts new deps.
    Returns (changed, old_spec_string).
    """
    text = _read_text(path)
    pattern = _make_pyproject_dep_re(dep_name)

    new_text_parts = []
    last_end = 0
    changed = False
    old_spec: Optional[str] = None

    for m in pattern.finditer(text):
        q = m.group("q")
        prefix = m.group("prefix")
        spec = m.group("spec")
        tail = m.group("tail")

        # Strip optional whitespace tail in spec for comparison
        existing = spec.rstrip()
        if existing == new_requirement:
            continue
        if _is_non_version_spec(existing):
            continue

        if old_spec is None:
            old_spec = existing

        new_text_parts.append(text[last_end:m.start()])
        new_text_parts.append(f"{q}{prefix}{new_requirement}{tail}{q}")
        last_end = m.end()
        changed = True

    if not changed:
        return False, None

    new_text_parts.append(text[last_end:])
    new_text = "".join(new_text_parts)

    if not dry_run:
        _write_text(path, new_text)
    return True, old_spec


__all__ = ["update_pyproject", "rewrite_pyproject_dep"]
