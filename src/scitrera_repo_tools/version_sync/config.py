"""versions.yaml schema validation and dataclasses."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml

from .strategies.base import validate_version

RESERVED_KEYS = (
    "preferred_versions",
    "project_rules",
    "dependency_mappings",
    "sources",
    "go_toolchain",
    "ci",
)


class ConfigError(ValueError):
    """Raised when versions.yaml fails schema validation."""


@dataclass(frozen=True)
class ProjectRule:
    type: str
    path: str
    args: tuple = field(default_factory=tuple)
    kwargs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreferredVersions:
    by_language: Mapping[str, Mapping[str, Optional[str]]] = field(default_factory=dict)

    def for_language(self, lang: str) -> Mapping[str, Optional[str]]:
        return self.by_language.get(lang, {})


@dataclass(frozen=True)
class DependencyMappings:
    packages: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    dependencies: Mapping[str, Mapping[str, List[str]]] = field(default_factory=dict)

    def language(self, lang: str) -> "_LangMapping":
        return _LangMapping(
            packages=self.packages.get(lang, {}),
            dependencies=self.dependencies.get(lang, {}),
        )


@dataclass(frozen=True)
class _LangMapping:
    packages: Mapping[str, str] = field(default_factory=dict)
    dependencies: Mapping[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SourcesConfig:
    by_language: Mapping[str, List[str]] = field(default_factory=dict)

    def for_language(self, lang: str) -> List[str]:
        return list(self.by_language.get(lang, []))


@dataclass(frozen=True)
class GoToolchainConfig:
    """Global Go-language directives applied to every discovered go.mod.

    - `go`         -> rewrites the `go X.Y[.Z]` directive
    - `toolchain`  -> rewrites the `toolchain goX.Y.Z` directive

    Both fields are optional and no-inject: a missing directive triggers a
    warning, not an addition.
    """
    go: Optional[str] = None
    toolchain: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return self.go is None and self.toolchain is None


@dataclass(frozen=True)
class CiPythonConfig:
    """Per-language CI knobs for python flows."""
    test_versions: tuple = ("3.11", "3.12", "3.13")
    lint: str = "ruff"                              # "ruff" | "none"
    install: str = 'pip install -e ".[test]"'
    pypi_environment: str = "pypi"


@dataclass(frozen=True)
class CiNpmConfig:
    """Per-language CI knobs for npm/typescript flows."""
    node_version: str = "24"
    lint: str = "tsc-noemit"                        # "tsc-noemit" | "eslint" | "none"
    npm_environment: str = "npm"
    use_provenance: bool = False
    use_oidc: bool = False


@dataclass(frozen=True)
class CiConfig:
    """Optional `ci:` block driving the `generate-ci` subcommand."""
    test_branches: tuple = ("main", "develop")
    python: CiPythonConfig = field(default_factory=CiPythonConfig)
    npm: CiNpmConfig = field(default_factory=CiNpmConfig)


@dataclass(frozen=True)
class SyncConfig:
    yaml_path: Path
    root: Path
    project_versions: Mapping[str, str]
    project_rules: Mapping[str, List[ProjectRule]]
    preferred_versions: PreferredVersions
    dependency_mappings: DependencyMappings
    sources: SourcesConfig
    go_toolchain: GoToolchainConfig = field(default_factory=lambda: GoToolchainConfig())
    ci: CiConfig = field(default_factory=CiConfig)


def _expect_mapping(value: Any, where: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected mapping, got {type(value).__name__}")
    return value


def _parse_project_rules(raw: Any, yaml_path: Path) -> Dict[str, List[ProjectRule]]:
    rules_map: Dict[str, List[ProjectRule]] = {}
    raw_map = _expect_mapping(raw, "project_rules")
    for project, entries in raw_map.items():
        if entries is None:
            rules_map[str(project)] = []
            continue
        if not isinstance(entries, list):
            raise ConfigError(
                f"project_rules['{project}']: expected list, got {type(entries).__name__}"
            )
        rules: List[ProjectRule] = []
        for idx, entry in enumerate(entries):
            if isinstance(entry, list) or isinstance(entry, tuple):
                raise ConfigError(
                    f"project_rules['{project}'][{idx}]: tuple/positional form is not "
                    "supported; use mapping form "
                    "'{ type: <strategy>, path: <path>, args?: [...], kwargs?: {...} }' "
                    f"(in {yaml_path})"
                )
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"project_rules['{project}'][{idx}]: expected mapping, "
                    f"got {type(entry).__name__}"
                )
            rtype = entry.get("type")
            rpath = entry.get("path")
            if not isinstance(rtype, str) or not rtype:
                raise ConfigError(
                    f"project_rules['{project}'][{idx}]: missing 'type'"
                )
            if not isinstance(rpath, str) or not rpath:
                raise ConfigError(
                    f"project_rules['{project}'][{idx}]: missing 'path'"
                )
            args_raw = entry.get("args", [])
            if args_raw is None:
                args_raw = []
            if not isinstance(args_raw, list):
                raise ConfigError(
                    f"project_rules['{project}'][{idx}].args: expected list"
                )
            kwargs_raw = entry.get("kwargs", {})
            if kwargs_raw is None:
                kwargs_raw = {}
            if not isinstance(kwargs_raw, dict):
                raise ConfigError(
                    f"project_rules['{project}'][{idx}].kwargs: expected mapping"
                )
            rules.append(
                ProjectRule(
                    type=rtype,
                    path=rpath,
                    args=tuple(args_raw),
                    kwargs=dict(kwargs_raw),
                )
            )
        rules_map[str(project)] = rules
    return rules_map


def _parse_preferred(raw: Any) -> PreferredVersions:
    by_lang: Dict[str, Dict[str, Optional[str]]] = {}
    raw_map = _expect_mapping(raw, "preferred_versions")
    for lang, deps in raw_map.items():
        deps_map = _expect_mapping(deps, f"preferred_versions['{lang}']")
        out: Dict[str, Optional[str]] = {}
        for name, val in deps_map.items():
            if val is None:
                out[str(name)] = None
            else:
                out[str(name)] = str(val)
        by_lang[str(lang)] = out
    return PreferredVersions(by_language=by_lang)


def _parse_dependency_mappings(raw: Any) -> DependencyMappings:
    packages: Dict[str, Dict[str, str]] = {}
    dependencies: Dict[str, Dict[str, List[str]]] = {}
    raw_map = _expect_mapping(raw, "dependency_mappings")
    for lang, block in raw_map.items():
        block_map = _expect_mapping(block, f"dependency_mappings['{lang}']")

        pkg_map = _expect_mapping(
            block_map.get("packages"), f"dependency_mappings['{lang}'].packages"
        )
        packages[str(lang)] = {str(k): str(v) for k, v in pkg_map.items()}

        dep_map_raw = _expect_mapping(
            block_map.get("dependencies"),
            f"dependency_mappings['{lang}'].dependencies",
        )
        dep_map: Dict[str, List[str]] = {}
        for consumer, deps in dep_map_raw.items():
            if not isinstance(deps, list):
                raise ConfigError(
                    f"dependency_mappings['{lang}'].dependencies['{consumer}']: "
                    "expected list"
                )
            dep_map[str(consumer)] = [str(x) for x in deps]
        dependencies[str(lang)] = dep_map
    return DependencyMappings(packages=packages, dependencies=dependencies)


def _parse_go_toolchain(raw: Any) -> GoToolchainConfig:
    if raw is None:
        return GoToolchainConfig()
    if not isinstance(raw, dict):
        raise ConfigError(
            f"go_toolchain: expected mapping, got {type(raw).__name__}"
        )
    go = raw.get("go")
    toolchain = raw.get("toolchain")
    if go is not None and not isinstance(go, (str, int, float)):
        raise ConfigError("go_toolchain.go: expected version string")
    if toolchain is not None and not isinstance(toolchain, (str, int, float)):
        raise ConfigError("go_toolchain.toolchain: expected version string")
    return GoToolchainConfig(
        go=str(go) if go is not None else None,
        toolchain=str(toolchain) if toolchain is not None else None,
    )


_CI_PYTHON_LINT_CHOICES = {"ruff", "none"}
_CI_NPM_LINT_CHOICES = {"tsc-noemit", "eslint", "none"}


def _parse_ci_python(raw: Any) -> CiPythonConfig:
    if raw is None:
        return CiPythonConfig()
    block = _expect_mapping(raw, "ci.python")
    kwargs: Dict[str, Any] = {}

    if "test_versions" in block:
        vers = block["test_versions"]
        if not isinstance(vers, list) or not vers:
            raise ConfigError("ci.python.test_versions: expected non-empty list of strings")
        kwargs["test_versions"] = tuple(str(v) for v in vers)
    if "lint" in block:
        lint = str(block["lint"])
        if lint not in _CI_PYTHON_LINT_CHOICES:
            raise ConfigError(
                f"ci.python.lint: expected one of {sorted(_CI_PYTHON_LINT_CHOICES)}, got '{lint}'"
            )
        kwargs["lint"] = lint
    if "install" in block:
        kwargs["install"] = str(block["install"])
    if "pypi_environment" in block:
        kwargs["pypi_environment"] = str(block["pypi_environment"])
    return CiPythonConfig(**kwargs)


def _parse_ci_npm(raw: Any) -> CiNpmConfig:
    if raw is None:
        return CiNpmConfig()
    block = _expect_mapping(raw, "ci.npm")
    kwargs: Dict[str, Any] = {}

    if "node_version" in block:
        kwargs["node_version"] = str(block["node_version"])
    if "lint" in block:
        lint = str(block["lint"])
        if lint not in _CI_NPM_LINT_CHOICES:
            raise ConfigError(
                f"ci.npm.lint: expected one of {sorted(_CI_NPM_LINT_CHOICES)}, got '{lint}'"
            )
        kwargs["lint"] = lint
    if "npm_environment" in block:
        kwargs["npm_environment"] = str(block["npm_environment"])
    if "use_provenance" in block:
        kwargs["use_provenance"] = bool(block["use_provenance"])
    if "use_oidc" in block:
        kwargs["use_oidc"] = bool(block["use_oidc"])
    return CiNpmConfig(**kwargs)


def _parse_ci(raw: Any) -> CiConfig:
    if raw is None:
        return CiConfig()
    block = _expect_mapping(raw, "ci")
    kwargs: Dict[str, Any] = {}

    if "test_branches" in block:
        branches = block["test_branches"]
        if not isinstance(branches, list) or not branches:
            raise ConfigError("ci.test_branches: expected non-empty list of branch names")
        kwargs["test_branches"] = tuple(str(b) for b in branches)
    if "python" in block:
        kwargs["python"] = _parse_ci_python(block["python"])
    if "npm" in block:
        kwargs["npm"] = _parse_ci_npm(block["npm"])
    return CiConfig(**kwargs)


def _parse_sources(raw: Any) -> SourcesConfig:
    by_lang: Dict[str, List[str]] = {}
    raw_map = _expect_mapping(raw, "sources")
    for lang, paths in raw_map.items():
        if paths is None:
            by_lang[str(lang)] = []
            continue
        if not isinstance(paths, list):
            raise ConfigError(f"sources['{lang}']: expected list of paths")
        by_lang[str(lang)] = [str(p) for p in paths]
    return SourcesConfig(by_language=by_lang)


def load_config(yaml_path: Path, *, root: Optional[Path] = None) -> SyncConfig:
    if not yaml_path.exists():
        raise ConfigError(f"versions.yaml not found at {yaml_path}")

    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"versions.yaml must be a YAML mapping, got {type(data).__name__}"
        )

    project_versions: Dict[str, str] = {}
    for key, val in data.items():
        if key in RESERVED_KEYS:
            continue
        ver = str(val)
        if not validate_version(ver):
            raise ConfigError(f"Invalid semver for '{key}': {ver}")
        project_versions[str(key)] = ver

    project_rules = _parse_project_rules(data.get("project_rules"), yaml_path)
    preferred = _parse_preferred(data.get("preferred_versions"))
    deps = _parse_dependency_mappings(data.get("dependency_mappings"))
    sources = _parse_sources(data.get("sources"))
    go_toolchain = _parse_go_toolchain(data.get("go_toolchain"))
    ci = _parse_ci(data.get("ci"))

    return SyncConfig(
        yaml_path=yaml_path,
        root=(root or yaml_path.parent).resolve(),
        project_versions=project_versions,
        project_rules=project_rules,
        preferred_versions=preferred,
        dependency_mappings=deps,
        sources=sources,
        go_toolchain=go_toolchain,
        ci=ci,
    )


__all__ = [
    "ConfigError",
    "ProjectRule",
    "PreferredVersions",
    "DependencyMappings",
    "SourcesConfig",
    "GoToolchainConfig",
    "CiPythonConfig",
    "CiNpmConfig",
    "CiConfig",
    "SyncConfig",
    "load_config",
    "RESERVED_KEYS",
]
