"""Shared regex patterns and I/O helpers for version-sync strategies."""

from __future__ import annotations

import re
from pathlib import Path

_RE_PYPROJECT_VERSION = re.compile(
    r'^(\s*version\s*=\s*")[^"]*(")', re.MULTILINE
)

_RE_INIT_VERSION = re.compile(
    r'''^(\s*__version__\s*=\s*['"])[^'"]*(['"])''', re.MULTILINE
)

# The original form: an exported `const Version = "..."` for importers to read.
# Still matched first — see `_RE_GO_VERSION_ANY`.
_RE_GO_VERSION_CONST = re.compile(
    r'^(\s*const\s+Version\s*=\s*")[^"]*(")', re.MULTILINE
)

# Also accepts the idiom a command uses: an unexported `var version = "..."`
# that `-ldflags "-X main.version=..."` overrides at build time. Its baked-in
# default is what `go install` and local builds report, so it drifts silently
# unless synced too. The optional `string` allows `var version string = "..."`.
_RE_GO_VERSION_ANY = re.compile(
    r'^(\s*(?:const|var)\s+[Vv]ersion(?:\s+string)?\s*=\s*")[^"]*(")', re.MULTILINE
)

# Retained as the broad pattern for callers that import it directly.
_RE_GO_VERSION = _RE_GO_VERSION_ANY

_RE_SEMVER = re.compile(
    r"^\d+\.\d+\.\d+"
    r"(?:-[0-9A-Za-z.-]+)?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


def _make_gomod_re(module_path: str) -> "re.Pattern[str]":
    escaped = re.escape(module_path)
    return re.compile(
        rf'(^[ \t]*(?:require[ \t]+)?{escaped}[ \t]+v)(\S+)',
        re.MULTILINE,
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def validate_version(version: str) -> bool:
    return bool(_RE_SEMVER.match(version))


__all__ = [
    "_RE_PYPROJECT_VERSION",
    "_RE_INIT_VERSION",
    "_RE_GO_VERSION",
    "_RE_GO_VERSION_CONST",
    "_RE_GO_VERSION_ANY",
    "_RE_SEMVER",
    "_make_gomod_re",
    "_read_text",
    "_write_text",
    "validate_version",
]
