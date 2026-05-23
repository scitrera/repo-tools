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
    "docker",
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
class CiGoConfig:
    """Per-language CI knobs for go flows."""
    go_version: Optional[str] = None        # default: derive from go_toolchain.go, else "1.25"
    lint: str = "golangci-lint"              # "golangci-lint" | "none"
    golangci_version: str = "v2.11.4"
    enable_govulncheck: bool = True
    test_args: str = "-race -count=1"


@dataclass(frozen=True)
class CiDockerConfig:
    """CI knobs for docker workflows."""
    default_platforms: tuple = ("linux/amd64", "linux/arm64")
    # Mapping of platform → runner; linux/amd64 defaults to ubuntu-latest implicitly.
    platform_runners: Mapping[str, str] = field(
        default_factory=lambda: {"linux/amd64": "ubuntu-latest"}
    )
    build_on_pr: bool = False
    enable_workflow_dispatch_version: bool = True
    # Which language test job sets to inline ahead of build jobs.
    test_prereqs: tuple = ("python", "npm", "go")


@dataclass(frozen=True)
class CiConfig:
    """Optional `ci:` block driving the `generate-ci-gha` subcommand."""
    test_branches: tuple = ("main", "develop")
    # Workflow basenames (no .yml) to skip entirely. Use when a generated
    # workflow has been hand-customized and you want the generator to stop
    # managing it. The on-disk file is left untouched and no drift is reported.
    skip_workflows: tuple = ()
    python: CiPythonConfig = field(default_factory=CiPythonConfig)
    npm: CiNpmConfig = field(default_factory=CiNpmConfig)
    go: CiGoConfig = field(default_factory=CiGoConfig)
    docker: CiDockerConfig = field(default_factory=CiDockerConfig)


@dataclass(frozen=True)
class DockerImage:
    """A single docker image build descriptor.

    `needs` is a single parent image name (or None). Multi-parent cascades
    are not supported in v1 (parser rejects list-valued `needs:`).
    """
    name: str
    context: str
    dockerfile: str
    tag_style: str = "standard"              # "standard" | "dev"
    platforms: Optional[tuple] = None        # default: ci.docker.default_platforms
    needs: Optional[str] = None
    version_from: Optional[str] = None
    base_image_arg: str = "BASE_IMAGE"
    build_strategy: str = "auto"             # "auto" | "qemu" | "native"


@dataclass(frozen=True)
class DockerConfig:
    """Optional `docker:` block driving the docker-build workflow."""
    ghcr: Optional[str] = None
    dockerhub: Optional[str] = None
    images: Mapping[str, DockerImage] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.images


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
    docker: DockerConfig = field(default_factory=DockerConfig)


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
_CI_GO_LINT_CHOICES = {"golangci-lint", "none"}
_DOCKER_TAG_STYLES = {"standard", "dev"}
_DOCKER_BUILD_STRATEGIES = {"auto", "qemu", "native"}
_DOCKER_TEST_PREREQ_CHOICES = {"python", "npm", "go"}


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


def _parse_ci_go(raw: Any) -> CiGoConfig:
    if raw is None:
        return CiGoConfig()
    block = _expect_mapping(raw, "ci.go")
    kwargs: Dict[str, Any] = {}

    if "go_version" in block:
        kwargs["go_version"] = str(block["go_version"])
    if "lint" in block:
        lint = str(block["lint"])
        if lint not in _CI_GO_LINT_CHOICES:
            raise ConfigError(
                f"ci.go.lint: expected one of {sorted(_CI_GO_LINT_CHOICES)}, got '{lint}'"
            )
        kwargs["lint"] = lint
    if "golangci_version" in block:
        kwargs["golangci_version"] = str(block["golangci_version"])
    if "enable_govulncheck" in block:
        kwargs["enable_govulncheck"] = bool(block["enable_govulncheck"])
    if "test_args" in block:
        kwargs["test_args"] = str(block["test_args"])
    return CiGoConfig(**kwargs)


def _parse_ci_docker(raw: Any) -> CiDockerConfig:
    if raw is None:
        return CiDockerConfig()
    block = _expect_mapping(raw, "ci.docker")
    kwargs: Dict[str, Any] = {}

    if "default_platforms" in block:
        plats = block["default_platforms"]
        if not isinstance(plats, list) or not plats:
            raise ConfigError("ci.docker.default_platforms: expected non-empty list")
        kwargs["default_platforms"] = tuple(str(p) for p in plats)
    if "platform_runners" in block:
        runners = _expect_mapping(block["platform_runners"], "ci.docker.platform_runners")
        # linux/amd64 → ubuntu-latest is always available; user can override.
        merged = {"linux/amd64": "ubuntu-latest"}
        merged.update({str(k): str(v) for k, v in runners.items()})
        kwargs["platform_runners"] = merged
    if "build_on_pr" in block:
        kwargs["build_on_pr"] = bool(block["build_on_pr"])
    if "enable_workflow_dispatch_version" in block:
        kwargs["enable_workflow_dispatch_version"] = bool(
            block["enable_workflow_dispatch_version"]
        )
    if "test_prereqs" in block:
        prereqs = block["test_prereqs"]
        if not isinstance(prereqs, list):
            raise ConfigError("ci.docker.test_prereqs: expected list")
        unknown = [p for p in prereqs if p not in _DOCKER_TEST_PREREQ_CHOICES]
        if unknown:
            raise ConfigError(
                f"ci.docker.test_prereqs: unknown entries {unknown}, "
                f"expected one of {sorted(_DOCKER_TEST_PREREQ_CHOICES)}"
            )
        kwargs["test_prereqs"] = tuple(str(p) for p in prereqs)
    return CiDockerConfig(**kwargs)


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
    if "skip_workflows" in block:
        skip = block["skip_workflows"]
        if not isinstance(skip, list):
            raise ConfigError(
                "ci.skip_workflows: expected list of workflow basenames (no .yml)"
            )
        kwargs["skip_workflows"] = tuple(str(s) for s in skip)
    if "python" in block:
        kwargs["python"] = _parse_ci_python(block["python"])
    if "npm" in block:
        kwargs["npm"] = _parse_ci_npm(block["npm"])
    if "go" in block:
        kwargs["go"] = _parse_ci_go(block["go"])
    if "docker" in block:
        kwargs["docker"] = _parse_ci_docker(block["docker"])
    return CiConfig(**kwargs)


def _parse_docker_image(name: str, raw: Any) -> DockerImage:
    block = _expect_mapping(raw, f"docker.images.{name}")
    if "context" not in block or not isinstance(block["context"], str):
        raise ConfigError(f"docker.images.{name}.context: required string")
    if "dockerfile" not in block or not isinstance(block["dockerfile"], str):
        raise ConfigError(f"docker.images.{name}.dockerfile: required string")
    kwargs: Dict[str, Any] = {
        "name": name,
        "context": block["context"],
        "dockerfile": block["dockerfile"],
    }
    if "tag_style" in block:
        ts = str(block["tag_style"])
        if ts not in _DOCKER_TAG_STYLES:
            raise ConfigError(
                f"docker.images.{name}.tag_style: expected one of "
                f"{sorted(_DOCKER_TAG_STYLES)}, got '{ts}'"
            )
        kwargs["tag_style"] = ts
    if "platforms" in block:
        plats = block["platforms"]
        if not isinstance(plats, list) or not plats:
            raise ConfigError(
                f"docker.images.{name}.platforms: expected non-empty list"
            )
        kwargs["platforms"] = tuple(str(p) for p in plats)
    if "needs" in block:
        needs = block["needs"]
        if isinstance(needs, list):
            raise ConfigError(
                f"docker.images.{name}.needs: multi-parent cascades are not "
                "supported in v1; use a single string"
            )
        if needs is not None:
            kwargs["needs"] = str(needs)
    if "version_from" in block:
        kwargs["version_from"] = str(block["version_from"])
    if "base_image_arg" in block:
        kwargs["base_image_arg"] = str(block["base_image_arg"])
    if "build_strategy" in block:
        bs = str(block["build_strategy"])
        if bs not in _DOCKER_BUILD_STRATEGIES:
            raise ConfigError(
                f"docker.images.{name}.build_strategy: expected one of "
                f"{sorted(_DOCKER_BUILD_STRATEGIES)}, got '{bs}'"
            )
        kwargs["build_strategy"] = bs
    return DockerImage(**kwargs)


def _parse_docker(raw: Any, project_versions: Mapping[str, str]) -> DockerConfig:
    if raw is None:
        return DockerConfig()
    block = _expect_mapping(raw, "docker")
    kwargs: Dict[str, Any] = {}

    if "ghcr" in block and block["ghcr"] is not None:
        kwargs["ghcr"] = str(block["ghcr"])
    if "dockerhub" in block and block["dockerhub"] is not None:
        kwargs["dockerhub"] = str(block["dockerhub"])

    images_raw = block.get("images")
    if images_raw is None:
        return DockerConfig(**kwargs)
    images_map = _expect_mapping(images_raw, "docker.images")
    images: Dict[str, DockerImage] = {}
    for img_name, img_block in images_map.items():
        images[str(img_name)] = _parse_docker_image(str(img_name), img_block)

    # Cross-image validation: every needs target must refer to a defined image.
    image_names = set(images)
    for img in images.values():
        if img.needs is not None and img.needs not in image_names:
            raise ConfigError(
                f"docker.images.{img.name}.needs: parent image "
                f"'{img.needs}' is not defined in docker.images"
            )
        if img.version_from is not None and img.version_from not in project_versions:
            raise ConfigError(
                f"docker.images.{img.name}.version_from: '{img.version_from}' "
                "is not a known project in versions.yaml"
            )

    kwargs["images"] = images
    return DockerConfig(**kwargs)


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
    docker = _parse_docker(data.get("docker"), project_versions)

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
        docker=docker,
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
    "CiGoConfig",
    "CiDockerConfig",
    "CiConfig",
    "DockerImage",
    "DockerConfig",
    "SyncConfig",
    "load_config",
    "RESERVED_KEYS",
]
