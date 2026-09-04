"""Topological ordering for dependency-aware publish jobs."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from typing import Dict, List, Optional

from ..version_sync.config import DockerImage, SyncConfig
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


@dataclass(frozen=True)
class DockerNode:
    """One docker image, its parent (if any), and its build strategy.

    `strategy` is the resolved strategy (`qemu`, `native`, or `cross`) after applying
    the `auto` default against `ci.docker.platform_runners`. Children use
    this to pick the right parent job-id (`build-<parent>` for qemu,
    `build-<parent>` for cross, or `merge-<parent>` for native).
    """
    name: str
    image: DockerImage
    needs: Optional[str]
    strategy: str          # "qemu" | "native" | "cross"


def _resolve_strategy(image: DockerImage, ci_docker, default_platforms: tuple) -> str:
    """Resolve `auto` → `qemu` or `native` based on the runner map."""
    if image.build_strategy in {"qemu", "native", "cross"}:
        return image.build_strategy
    platforms = image.platforms or default_platforms
    runners = ci_docker.platform_runners
    if all(p in runners for p in platforms):
        return "native"
    return "qemu"


def docker_order(config: SyncConfig) -> List[DockerNode]:
    """Topologically order docker images, leaves first.

    `image.needs` defines the cascade edge (child → parent). Cycles raise
    `ValueError`. `strategy` resolution is applied here, not at config-parse
    time, because it depends on `ci.docker.platform_runners`.
    """
    images = config.docker.images
    if not images:
        return []

    ci_docker = config.ci.docker
    edges: Dict[str, List[str]] = {n: [] for n in sorted(images)}
    for name in sorted(images):
        parent = images[name].needs
        if parent is not None and parent in images:
            edges[name].append(parent)

    # Strategy=native + missing runner is a configuration error.
    for img in images.values():
        if img.build_strategy == "native":
            platforms = img.platforms or ci_docker.default_platforms
            missing = [p for p in platforms if p not in ci_docker.platform_runners]
            if missing:
                raise ValueError(
                    f"docker.images.{img.name}.build_strategy=native but "
                    f"no platform_runners entry for: {missing}"
                )

    sorter: TopologicalSorter[str] = TopologicalSorter()
    for node, preds in edges.items():
        sorter.add(node, *preds)

    try:
        ordered = list(sorter.static_order())
    except CycleError as exc:
        raise ValueError(
            f"Cyclic docker dependency: {exc.args[1]}"
        ) from exc

    result: List[DockerNode] = []
    for name in ordered:
        img = images[name]
        result.append(
            DockerNode(
                name=name,
                image=img,
                needs=img.needs if img.needs in images else None,
                strategy=_resolve_strategy(img, ci_docker, ci_docker.default_platforms),
            )
        )
    return result


__all__ = ["PublishNode", "publish_order", "DockerNode", "docker_order"]
