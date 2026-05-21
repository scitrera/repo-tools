"""Orchestrates phases A (project versions), B (deps mappings), C (preferred), D (sources)."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .config import SyncConfig
from .discovery import manifests_for_language as _manifests_for_language
from .normalize import normalize_go, normalize_python, normalize_typescript
from .sources import SOURCE_READER_MAP, detect_reader
from .strategies import STRATEGY_MAP
from .strategies.gomod_directives import (
    update_gomod_go_directive,
    update_gomod_toolchain_directive,
)
from .strategies.gomod_require import rewrite_gomod_require
from .strategies.package_json import rewrite_package_json_dep
from .strategies.pyproject import rewrite_pyproject_dep

logger = logging.getLogger("scitrera_repo_tools.version_sync")

ChangeRecord = Tuple[Path, str, Optional[str], str]

_NORMALIZERS = {
    "python": normalize_python,
    "typescript": normalize_typescript,
    "go": normalize_go,
}

_REWRITERS = {
    "python": rewrite_pyproject_dep,
    "typescript": rewrite_package_json_dep,
    "go": rewrite_gomod_require,
}


def _phase_a(
    config: SyncConfig,
    *,
    check: bool,
    verbose: bool,
    changes: List[ChangeRecord],
    errors: List[str],
) -> None:
    for project, target_version in sorted(config.project_versions.items()):
        rules = config.project_rules.get(project)
        if rules is None:
            errors.append(
                f"'{project}' is in versions.yaml but has no entry in 'project_rules'"
            )
            continue
        if not rules:
            if verbose:
                logger.debug("  %s: no files to update (version tracked externally)", project)
            continue
        for rule in rules:
            abs_path = (config.root / rule.path).resolve()
            if not abs_path.exists():
                errors.append(f"File not found: {abs_path}")
                continue
            updater = STRATEGY_MAP.get(rule.type)
            if updater is None:
                errors.append(
                    f"Unknown strategy '{rule.type}' for project '{project}' "
                    f"(rule path: {rule.path})"
                )
                continue
            try:
                changed, old_version = updater(
                    abs_path, target_version, check, *rule.args, **rule.kwargs
                )
            except TypeError as exc:
                errors.append(
                    f"Strategy '{rule.type}' for '{project}' ({rule.path}) raised: {exc}"
                )
                continue

            label = str(rule.path)
            if rule.args:
                label = f"{rule.path} [{', '.join(map(str, rule.args))}]"

            if changed:
                changes.append((abs_path, "version", old_version, target_version))
                msg = f"  {label}: {old_version} -> {target_version}"
                if verbose or check:
                    logger.info(msg)
            elif verbose:
                logger.info("  %s: already %s", label, target_version)


def _phase_b(
    config: SyncConfig,
    *,
    check: bool,
    verbose: bool,
    release: bool,
    changes: List[ChangeRecord],
    errors: List[str],
    touched: Set[Tuple[Path, str]],
) -> None:
    for lang, normalizer in _NORMALIZERS.items():
        rewriter = _REWRITERS[lang]
        lang_map = config.dependency_mappings.language(lang)
        if not lang_map.dependencies:
            continue
        manifests = _manifests_for_language(config, lang)
        package_map = lang_map.packages
        for consumer, internal_deps in lang_map.dependencies.items():
            manifest = manifests.get(consumer)
            if manifest is None:
                errors.append(
                    f"dependency_mappings.{lang}.dependencies: consumer '{consumer}' "
                    "has no matching manifest rule in 'project_rules'"
                )
                continue
            if not manifest.exists():
                errors.append(f"Manifest not found for consumer '{consumer}': {manifest}")
                continue
            for internal_dep in internal_deps:
                external_name = package_map.get(internal_dep)
                if external_name is None:
                    errors.append(
                        f"dependency_mappings.{lang}: internal dep '{internal_dep}' "
                        "is not declared in 'packages' map"
                    )
                    continue
                version = config.project_versions.get(internal_dep)
                if version is None:
                    errors.append(
                        f"dependency_mappings.{lang}: internal dep '{internal_dep}' "
                        "has no top-level version in versions.yaml"
                    )
                    continue
                requirement = normalizer(version)
                try:
                    changed, old_spec = rewriter(
                        manifest, external_name, requirement, check,
                        resolve_local_refs=release,
                    )
                except Exception as exc:
                    errors.append(
                        f"Failed to rewrite {external_name} in {manifest}: {exc}"
                    )
                    continue
                touched.add((manifest, external_name))
                if changed:
                    changes.append((manifest, external_name, old_spec, requirement))
                    msg = f"  {manifest}: {external_name} {old_spec} -> {requirement}"
                    if verbose or check:
                        logger.info(msg)
                elif verbose:
                    logger.info("  %s: %s already %s", manifest, external_name, requirement)


def _phase_c(
    config: SyncConfig,
    *,
    check: bool,
    verbose: bool,
    release: bool,
    changes: List[ChangeRecord],
    errors: List[str],
    touched: Set[Tuple[Path, str]],
    pending_for_phase_d: Dict[str, List[Tuple[Path, str]]],
) -> None:
    for lang, normalizer in _NORMALIZERS.items():
        rewriter = _REWRITERS[lang]
        deps_map = config.preferred_versions.for_language(lang)
        if not deps_map:
            continue
        manifests = _manifests_for_language(config, lang)
        if not manifests:
            continue
        for dep_name, raw_value in deps_map.items():
            if raw_value is None:
                for manifest in manifests.values():
                    pending_for_phase_d.setdefault(lang, []).append((manifest, dep_name))
                continue
            requirement = normalizer(raw_value)
            for manifest in manifests.values():
                key = (manifest, dep_name)
                if key in touched:
                    continue
                if not manifest.exists():
                    continue
                try:
                    changed, old_spec = rewriter(
                        manifest, dep_name, requirement, check,
                        resolve_local_refs=release,
                    )
                except Exception as exc:
                    errors.append(
                        f"Failed to rewrite {dep_name} in {manifest}: {exc}"
                    )
                    continue
                touched.add(key)
                if changed:
                    changes.append((manifest, dep_name, old_spec, requirement))
                    msg = f"  {manifest}: {dep_name} {old_spec} -> {requirement}"
                    if verbose or check:
                        logger.info(msg)
                elif verbose:
                    logger.info("  %s: %s already %s", manifest, dep_name, requirement)


def _phase_d(
    config: SyncConfig,
    *,
    check: bool,
    verbose: bool,
    release: bool,
    changes: List[ChangeRecord],
    errors: List[str],
    touched: Set[Tuple[Path, str]],
    pending_for_phase_d: Dict[str, List[Tuple[Path, str]]],
) -> None:
    if not pending_for_phase_d:
        return

    cache: Dict[str, Dict[str, Dict[str, str]]] = {}  # lang -> {path_str: {name: version}}
    for lang, items in pending_for_phase_d.items():
        normalizer = _NORMALIZERS.get(lang)
        rewriter = _REWRITERS.get(lang)
        if normalizer is None or rewriter is None:
            continue
        source_paths = config.sources.for_language(lang)
        if not source_paths:
            for manifest, dep_name in items:
                logger.warning(
                    "preferred_versions.%s.%s is null and no sources configured; leaving unchanged",
                    lang, dep_name,
                )
            continue

        per_lang_cache = cache.setdefault(lang, {})

        for manifest, dep_name in items:
            key = (manifest, dep_name)
            if key in touched:
                continue
            resolved: Optional[str] = None
            for src_rel in source_paths:
                src_abs = (config.root / src_rel).resolve()
                src_key = str(src_abs)
                if src_key not in per_lang_cache:
                    if not src_abs.exists():
                        per_lang_cache[src_key] = {}
                        continue
                    reader_name = detect_reader(src_abs)
                    if reader_name is None:
                        logger.warning("Could not detect reader for %s", src_abs)
                        per_lang_cache[src_key] = {}
                        continue
                    reader = SOURCE_READER_MAP.get(reader_name)
                    if reader is None:
                        per_lang_cache[src_key] = {}
                        continue
                    try:
                        per_lang_cache[src_key] = reader(src_abs)
                    except Exception as exc:
                        errors.append(f"Failed to read source {src_abs}: {exc}")
                        per_lang_cache[src_key] = {}
                        continue
                version = per_lang_cache[src_key].get(dep_name)
                if version is not None:
                    resolved = version
                    break

            if resolved is None:
                logger.warning(
                    "preferred_versions.%s.%s: unresolved (no source provided a version)",
                    lang, dep_name,
                )
                continue

            requirement = normalizer(resolved)
            if not manifest.exists():
                continue
            try:
                changed, old_spec = rewriter(
                    manifest, dep_name, requirement, check,
                    resolve_local_refs=release,
                )
            except Exception as exc:
                errors.append(f"Failed to rewrite {dep_name} in {manifest}: {exc}")
                continue
            touched.add(key)
            if changed:
                changes.append((manifest, dep_name, old_spec, requirement))
                msg = f"  {manifest}: {dep_name} {old_spec} -> {requirement} (from source)"
                if verbose or check:
                    logger.info(msg)
            elif verbose:
                logger.info(
                    "  %s: %s already %s (from source)", manifest, dep_name, requirement
                )


def _phase_e_go_toolchain(
    config: SyncConfig,
    *,
    check: bool,
    verbose: bool,
    changes: List[ChangeRecord],
    errors: List[str],
) -> None:
    """Update top-level `go` and `toolchain` directives in every discovered go.mod."""
    tc = config.go_toolchain
    if tc.is_empty:
        return

    manifests = _manifests_for_language(config, "go")
    if not manifests:
        if verbose:
            logger.debug("go_toolchain configured but no go.mod manifests found.")
        return

    seen: Set[Path] = set()
    for manifest in manifests.values():
        if manifest in seen:
            continue
        seen.add(manifest)
        if not manifest.exists():
            errors.append(f"go.mod not found for go_toolchain phase: {manifest}")
            continue

        if tc.go is not None:
            try:
                changed, old = update_gomod_go_directive(manifest, tc.go, check)
            except Exception as exc:
                errors.append(f"Failed to update `go` directive in {manifest}: {exc}")
            else:
                if changed:
                    changes.append((manifest, "go-directive", old, tc.go))
                    msg = f"  {manifest}: go {old} -> {tc.go}"
                    if verbose or check:
                        logger.info(msg)
                elif verbose:
                    logger.info("  %s: go already %s", manifest, tc.go)

        if tc.toolchain is not None:
            try:
                changed, old = update_gomod_toolchain_directive(
                    manifest, tc.toolchain, check
                )
            except Exception as exc:
                errors.append(
                    f"Failed to update `toolchain` directive in {manifest}: {exc}"
                )
            else:
                if changed:
                    new_repr = f"go{tc.toolchain}" if not tc.toolchain.startswith("go") else tc.toolchain
                    changes.append((manifest, "toolchain-directive", old, new_repr))
                    msg = f"  {manifest}: toolchain {old} -> {new_repr}"
                    if verbose or check:
                        logger.info(msg)
                elif verbose:
                    logger.info("  %s: toolchain already %s", manifest, tc.toolchain)


def run(
    config: SyncConfig,
    *,
    check: bool = False,
    verbose: bool = False,
    release: bool = False,
) -> int:
    """Synchronize versions per `config`.

    `release=True` (opt-in) rewrites local-reference dep specifiers
    (`file:`, `workspace:`, `link:`, git/url, PEP 508 `@ git+...`) into
    canonical version pins. Use BEFORE publishing to PyPI/npm.
    Default `False` preserves local refs for normal development.
    """
    changes: List[ChangeRecord] = []
    errors: List[str] = []
    touched: Set[Tuple[Path, str]] = set()
    pending_for_phase_d: Dict[str, List[Tuple[Path, str]]] = {}

    if release:
        logger.info("Running in --release mode: local refs will be rewritten to version pins.")

    _phase_a(config, check=check, verbose=verbose, changes=changes, errors=errors)
    _phase_b(
        config,
        check=check,
        verbose=verbose,
        release=release,
        changes=changes,
        errors=errors,
        touched=touched,
    )
    _phase_c(
        config,
        check=check,
        verbose=verbose,
        release=release,
        changes=changes,
        errors=errors,
        touched=touched,
        pending_for_phase_d=pending_for_phase_d,
    )
    _phase_d(
        config,
        check=check,
        verbose=verbose,
        release=release,
        changes=changes,
        errors=errors,
        touched=touched,
        pending_for_phase_d=pending_for_phase_d,
    )
    _phase_e_go_toolchain(
        config,
        check=check,
        verbose=verbose,
        changes=changes,
        errors=errors,
    )

    if errors:
        logger.error("Errors encountered:")
        for e in errors:
            logger.error("  %s", e)

    if check:
        if changes:
            logger.error("Version drift detected (%d change(s) needed):", len(changes))
            for path, field_name, old, new in changes:
                logger.error("  %s: %s %s -> %s", path, field_name, old, new)
            return 1
        if errors:
            return 1
        logger.info("All versions in sync.")
        return 0

    if changes:
        logger.info("Updated %d entry/entries:", len(changes))
        for path, field_name, old, new in changes:
            logger.info("  %s: %s %s -> %s", path, field_name, old, new)
    else:
        logger.info("All versions already in sync - nothing to update.")

    return 1 if errors else 0


__all__ = ["run", "ChangeRecord"]
