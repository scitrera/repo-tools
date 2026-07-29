"""Manifest discovery helpers shared across subcommands."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path
from typing import Dict

from .config import SyncConfig

_PY_MANIFEST_TYPES = ("pyproject",)
_TS_MANIFEST_TYPES = ("package",)
# Ordered by precedence, not membership. `gomod` declares the project's module
# outright; `gomod_require` is only a fallback for repos predating it, where the
# module happened to coincide with the file whose require lines get pinned.
# Those two coincide far less often than they look: a module with no in-repo
# requires has no `gomod_require` rule at all, and a project whose only such
# rule targets a nested module would otherwise point its whole Go lane at the
# wrong directory.
_GO_MANIFEST_TYPES = ("gomod", "gomod_require")

_LANG_MANIFEST_TYPES = {
    "python": _PY_MANIFEST_TYPES,
    "typescript": _TS_MANIFEST_TYPES,
    "go": _GO_MANIFEST_TYPES,
}


def manifests_for_language(config: SyncConfig, lang: str) -> Dict[str, Path]:
    """Return {project_name: manifest_path} for projects with a manifest of this language.

    When a language lists several rule types, earlier ones win outright: a
    project with both a `gomod` and a `gomod_require` rule resolves to the
    `gomod` one regardless of declaration order in versions.yaml.
    """
    types = _LANG_MANIFEST_TYPES.get(lang, ())
    out: Dict[str, Path] = {}
    for project, rules in config.project_rules.items():
        for rule_type in types:
            match = next((r for r in rules if r.type == rule_type), None)
            if match is not None:
                out[project] = (config.root / match.path).resolve()
                break
    return out


__all__ = [
    "manifests_for_language",
    "_LANG_MANIFEST_TYPES",
    "_PY_MANIFEST_TYPES",
    "_TS_MANIFEST_TYPES",
    "_GO_MANIFEST_TYPES",
]
