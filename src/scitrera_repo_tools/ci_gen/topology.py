"""Topological ordering for dependency-aware publish jobs."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from typing import Dict, List

from ..version_sync.config import SyncConfig
from ..version_sync.discovery import manifests_for_language


@dataclass(frozen=True)
class PublishNode:
    """One publishable project plus its in-language predecessor projects.

    `needs` lists *project names from versions.yaml* (not GitHub job ids); the
    template layer maps those to job ids.
    """
    name: str
    needs: tuple


def publish_order(config: SyncConfig, lang: str) -> List[PublishNode]:
    """Return publishable projects of `lang`, toposorted leaves-first.

    Edges come from `dependency_mappings.<lang>.dependencies` — a consumer must
    publish *after* every internal dep it requires. Independent projects come
    out in alphabetical order for deterministic output.
    """
    manifests = manifests_for_language(config, lang)
    if not manifests:
        return []

    publishable = set(manifests)
    lang_map = config.dependency_mappings.language(lang)

    # Insertion order drives `static_order()` tie-breaks within a ready-layer;
    # sort up front so independent projects come out alphabetically.
    edges: Dict[str, List[str]] = {p: [] for p in sorted(publishable)}
    for consumer in sorted(lang_map.dependencies):
        if consumer not in publishable:
            continue
        for dep in sorted(lang_map.dependencies[consumer]):
            if dep in publishable:
                edges[consumer].append(dep)

    sorter: TopologicalSorter[str] = TopologicalSorter()
    for node, preds in edges.items():
        sorter.add(node, *preds)

    try:
        ordered = list(sorter.static_order())
    except CycleError as exc:
        raise ValueError(
            f"Cyclic publish dependency in {lang}: {exc.args[1]}"
        ) from exc

    result: List[PublishNode] = []
    for name in ordered:
        result.append(PublishNode(name=name, needs=tuple(sorted(edges[name]))))
    return result


__all__ = ["PublishNode", "publish_order"]
