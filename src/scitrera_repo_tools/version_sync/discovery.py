"""Manifest discovery helpers shared across subcommands."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .config import SyncConfig

_PY_MANIFEST_TYPES = {"pyproject"}
_TS_MANIFEST_TYPES = {"package"}
_GO_MANIFEST_TYPES = {"gomod_require"}

_LANG_MANIFEST_TYPES = {
    "python": _PY_MANIFEST_TYPES,
    "typescript": _TS_MANIFEST_TYPES,
    "go": _GO_MANIFEST_TYPES,
}


def manifests_for_language(config: SyncConfig, lang: str) -> Dict[str, Path]:
    """Return {project_name: manifest_path} for projects with a manifest of this language."""
    types = _LANG_MANIFEST_TYPES.get(lang, set())
    out: Dict[str, Path] = {}
    for project, rules in config.project_rules.items():
        for rule in rules:
            if rule.type in types:
                out[project] = (config.root / rule.path).resolve()
                break
    return out


__all__ = [
    "manifests_for_language",
    "_LANG_MANIFEST_TYPES",
    "_PY_MANIFEST_TYPES",
    "_TS_MANIFEST_TYPES",
    "_GO_MANIFEST_TYPES",
]
