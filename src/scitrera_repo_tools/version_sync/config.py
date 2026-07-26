"""versions.yaml schema validation and dataclasses."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import yaml

from .normalize import normalize_go
from .strategies.base import validate_version

RESERVED_KEYS = (
    "preferred_versions",
    "project_rules",
    "dependency_mappings",
    "sources",
    "go_toolchain",
    "ci",
    "docker",
    "proto",
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
class CiStep:
    """One caller-supplied step injected into a generated test job.

    Deliberately narrow: a name and a shell command. Generated workflows are
    meant to be regenerated, so this is an escape hatch for the one or two
    repo-specific things a template cannot know about — freeing disk before a
    heavy test run, or a regression gate that is not a test — not a general
    workflow authoring surface.
    """
    name: str
    run: str
    if_expr: Optional[str] = None            # YAML key is `if`
    working_directory: Optional[str] = None  # None = the project's own directory


@dataclass(frozen=True)
class CiPythonProject:
    """Per-project overrides for one python project's test job.

    Exists because a monorepo's packages rarely share one install line: a server
    needs its optional extras to import at all, while a thin SDK needs none of
    them. A single global `install` forces the union on every project, which
    installs unrelated heavy dependencies and hides which package actually
    requires what.
    """
    install: Optional[str] = None
    test_command: Optional[str] = None
    setup_steps: tuple = ()
    extra_steps: tuple = ()


@dataclass(frozen=True)
class CiPythonConfig:
    """Per-language CI knobs for python flows.

    The two publish-side knobs exist because a tag push is irreversible once
    it reaches PyPI: `publish_requires_tests` gates the upload on the same
    matrix the test workflow runs, and `verify_tag_version` refuses to publish
    when the pushed tag disagrees with versions.yaml. `verify_tag_version` names
    a project rather than defaulting to "the" project because a single `v*.*.*`
    tag cannot identify a project in a multi-project repo.
    """
    test_versions: tuple = ("3.11", "3.12", "3.13")
    lint: str = "ruff"                              # "ruff" | "none"
    # Also run `ruff format --check`. Separate from `lint` because formatting
    # and linting fail for different reasons and a repo may enforce only one.
    format_check: bool = False
    install: str = 'pip install -e ".[test]"'
    test_command: str = "python -m pytest -v"
    setup_steps: tuple = ()                         # injected before lint/install
    extra_steps: tuple = ()                         # injected after the test step
    # Per-project overrides, keyed by project name. Anything unset falls back to
    # the language-level value above.
    projects: Mapping[str, CiPythonProject] = field(default_factory=dict)
    pypi_environment: str = "pypi"
    publish_requires_tests: bool = True
    verify_tag_version: Optional[str] = None        # project name, or None to disable
    # Projects to generate publish jobs for. Empty means every python project.
    # A manifest is not a statement of intent to publish: a repo can hold a
    # package that ships only as a container image, and generating a PyPI job
    # for it risks an unintended first public release rather than a failure.
    publish_projects: tuple = ()
    # Skip the upload when the registry already serves this version. Repos whose
    # packages are versioned independently republish an unchanged version on
    # every tag, which PyPI/npm reject outright and which fails the release.
    skip_if_published: bool = False


@dataclass(frozen=True)
class CiNpmConfig:
    """Per-language CI knobs for npm/typescript flows."""
    node_version: str = "24"
    lint: str = "tsc-noemit"                        # "tsc-noemit" | "eslint" | "none"
    # Run `npm run build --if-present` in test jobs. Required when packages
    # reference each other with `file:` specifiers: the consumer type-checks
    # against the producer's built output, and npm does not run `prepublishOnly`
    # for a `file:` dependency, so nothing else creates that output.
    build: bool = False
    # Enable actions/setup-node dependency caching. Off by default because it
    # requires a lockfile at the resolved path and fails the job without one.
    cache: bool = False
    npm_environment: str = "npm"
    use_provenance: bool = False
    use_oidc: bool = False
    # Gate the publish on the same tests the test workflow runs. An npm publish
    # is irrevocable in practice (unpublish is heavily restricted), so the
    # default matches the python side rather than shipping untested code.
    publish_requires_tests: bool = True
    # See CiPythonConfig for the rationale behind both of these.
    publish_projects: tuple = ()
    skip_if_published: bool = False


@dataclass(frozen=True)
class GovulncheckIgnore:
    """One accepted-risk advisory.

    `projects` scopes the waiver to specific Go modules. Empty means every
    module, which is right for a repo-wide dependency but wrong when only one
    module reaches the vulnerable code — the others would then report the entry
    as stale on every run, which trains people to ignore that warning.
    """
    id: str
    reason: str
    projects: tuple = ()

    def applies_to(self, project: str) -> bool:
        return not self.projects or project in self.projects


@dataclass(frozen=True)
class CiGoConfig:
    """Per-language CI knobs for go flows."""
    go_version: Optional[str] = None        # default: derive from go_toolchain.go, else "1.25"
    lint: str = "golangci-lint"              # "golangci-lint" | "none"
    golangci_version: str = "v2.11.4"
    enable_govulncheck: bool = True
    test_args: str = "-race -count=1"
    # Append coverage flags to `go test` and upload the profile as an artifact.
    # One switch rather than two, because hand-writing `-coverprofile` into
    # test_args and separately remembering to enable the upload is how a repo
    # ends up generating a coverage file that nothing collects.
    coverage: bool = False
    # How publish-go handles the per-module tags Go requires for nested modules.
    #   none   - do not generate publish-go.yml (default)
    #   verify - fail the release when a module tag is missing or points elsewhere
    #   push   - additionally create and push any missing tag (contents: write)
    # Publishing a Go module is only tag existence — there is no artifact to
    # upload — so "publishing" here means getting `<dir>/vX.Y.Z` onto the commit
    # the release tag names. Opt-in by default: enabling it also turns on a
    # module-path/directory consistency check that can legitimately fail a repo
    # whose layout was never valid for `go get`.
    module_tags: str = "none"
    # govulncheck itself is a tool whose findings change over time; pin it so an
    # upstream release cannot redden an unrelated PR.
    govulncheck_version: str = "v1.1.4"
    # Advisories to treat as accepted risk, as {id, reason} pairs. govulncheck
    # has no native suppression, so the generated job filters its JSON output
    # against this list. A reason is required: an allow-list entry is a security
    # decision and must say who decided what. Entries that no longer match any
    # finding are reported so the list cannot quietly rot.
    govulncheck_ignore: tuple = ()


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
    # Branches whose *pushes* trigger the test workflows. Empty means "same as
    # test_branches". Narrowing this is the only way to avoid running every
    # check twice for one commit: a branch that is both in the push list and the
    # head of an open PR fires `push` and `pull_request` together, and the
    # redundant run can only ever be cancelled — GitHub reports it as cancelled,
    # never as success, and a cancelled required check can hold up a merge.
    # Setting this to just the default branch keeps post-merge validation while
    # leaving pre-merge validation to the PR event.
    push_branches: tuple = ()
    # How generated workflows provision scitrera-repo-tools before invoking
    # `sync-versions`. `uvx` mirrors what the `scripts/` shims do locally
    # (resolve on demand, no persistent install) so CI and developer machines
    # run the same resolution path; `pip` is the escape hatch for runners
    # without uv.
    bootstrap_method: str = "uvx"                        # "uvx" | "pip"
    # What to resolve repo-tools *from*. Any uv/pip source spec: a PyPI name
    # (optionally pinned), a `git+https://...@ref` URL, or a local path. The
    # repo-tools repo itself sets `.` so its workflows exercise the checked-out
    # tree rather than a previously published artifact.
    repo_tools_source: str = "scitrera-repo-tools"
    # Workflow basenames (no .yml) to skip entirely. Use when a generated
    # workflow has been hand-customized and you want the generator to stop
    # managing it. The on-disk file is left untouched and no drift is reported.
    skip_workflows: tuple = ()
    # Workflow basenames (no .yml) to manage *exclusively*. Empty means "manage
    # everything that renders". This is the inverse of skip_workflows and the
    # better fit for incremental adoption: a repo taking on one generated
    # workflow at a time would otherwise have to enumerate every workflow it
    # does not want, and revisit that list each time a new generator is added.
    # Applied before skip_workflows, which can still subtract from it.
    only_workflows: tuple = ()
    # Attach built distributions to a GitHub Release for the pushed tag.
    # Lives at `ci:` level rather than under `ci.python` because a single
    # `v*.*.*` tag in a polyglot repo drives the Go, Python, npm and container
    # releases together — the release is a property of the tag, not of one
    # language's publish flow.
    github_release: bool = False
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
    # Pushed repository name, when it must differ from the descriptor key.
    # Two descriptors can target one repository distinguished only by tag —
    # e.g. a `dev`-tagged variant published as `myimg:dev-*` alongside
    # `myimg:*` — which is impossible if the key doubles as the image name.
    image_name: Optional[str] = None
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
class ProtoToolchainConfig:
    """Exact pins for every binary that participates in proto codegen.

    These are *toolchain* pins, not manifest dependencies: unlike
    `preferred_versions`, nothing rewrites these into a manifest file. They are
    read by `compile-protos`, which verifies the installed tools before
    generating anything — so a compiler mismatch fails loudly instead of
    silently emitting artifacts whose embedded version headers drift.

    `protoc` and `grpcio_tools` are two *independent* compilers: `grpc_tools`
    bundles its own libprotoc, so the pair must be reconciled deliberately
    rather than assumed consistent. `compile-protos` cross-checks them.

    Versions are stored as written except the two Go plugin pins, which are
    normalized to Go's `v`-prefixed module form so they can be fed straight to
    `go install <pkg>@<version>`.
    """
    protoc: Optional[str] = None
    protoc_gen_go: Optional[str] = None
    protoc_gen_go_grpc: Optional[str] = None
    grpcio_tools: Optional[str] = None
    proto_loader: Optional[str] = None


@dataclass(frozen=True)
class ProtoGoOutput:
    """Go codegen target (`protoc-gen-go` + `protoc-gen-go-grpc`)."""
    path: str
    paths: str = "source_relative"       # "source_relative" | "import"
    grpc: bool = True
    gofmt: bool = True


@dataclass(frozen=True)
class ProtoPythonOutput:
    """Python codegen target (`grpc_tools.protoc`).

    `fix_relative_imports` addresses a universal protobuf-Python problem rather
    than a project quirk: generated `_pb2_grpc.py` / cross-importing `_pb2.py`
    modules reference their siblings by bare `import foo_pb2`, which fails once
    the generated code lives inside a package.
    """
    path: str
    stubs: bool = True                   # --pyi_out
    grpc: bool = True
    fix_relative_imports: bool = True
    ensure_init_py: bool = True


@dataclass(frozen=True)
class ProtoTypeScriptOutput:
    """TypeScript codegen target.

    `generator` is an extension point: the emitted output shape differs
    fundamentally between generators, so the choice is modelled in config from
    the start even though only `proto-loader` is wired up today. The runner
    reports unimplemented generators explicitly.

    `package_dir` is the npm package root whose `node_modules/.bin` holds the
    generator binary. When omitted it is discovered by walking up from `path`
    to the nearest `package.json`.
    """
    path: str
    generator: str = "proto-loader"       # proto-loader | ts-proto | protoc-gen-ts
    grpc_lib: str = "@grpc/grpc-js"
    package_dir: Optional[str] = None
    options: tuple = (
        "--longs=String",
        "--enums=String",
        "--defaults",
        "--oneofs",
        "--includeComments",
    )


@dataclass(frozen=True)
class ProtoConfig:
    """Optional `proto:` block driving the `compile-protos` subcommand.

    Inputs (`dir`, `files`), toolchain pins and per-language outputs live
    together deliberately: pins divorced from the code that consumes them are
    how a pin silently becomes inert.
    """
    dir: Optional[str] = None
    files: tuple = ()
    toolchain: ProtoToolchainConfig = field(default_factory=ProtoToolchainConfig)
    go: Optional[ProtoGoOutput] = None
    python: Optional[ProtoPythonOutput] = None
    typescript: Optional[ProtoTypeScriptOutput] = None

    @property
    def is_empty(self) -> bool:
        return self.dir is None or not self.files

    @property
    def languages(self) -> tuple:
        """Enabled output languages, in deterministic order."""
        out = []
        if self.go is not None:
            out.append("go")
        if self.python is not None:
            out.append("python")
        if self.typescript is not None:
            out.append("typescript")
        return tuple(out)


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
    proto: ProtoConfig = field(default_factory=ProtoConfig)


def _reject_unknown(block: Mapping[str, Any], allowed: Iterable[str], where: str) -> None:
    """Fail on unrecognized keys.

    Stricter than this file's original behavior, which silently ignored keys it
    did not recognize. A misspelled key reads as configuration that is being
    honored while doing nothing at all — the failure mode that made a pinned
    `grpcio-tools` inert and would have let a typo'd `only_workflows` manage
    every workflow instead of one.

    Note this only protects against typos, not against a *newer* key read by an
    *older* repo-tools: that version cannot know the key exists. Pinning
    `ci.repo_tools_source` is what guards against version skew.
    """
    unknown = sorted(set(block) - set(allowed))
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {unknown}; expected one of {sorted(allowed)}"
        )


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


_CI_BOOTSTRAP_METHODS = {"uvx", "pip"}
_CI_KEYS = (
    "test_branches",
    "push_branches",
    "bootstrap_method",
    "repo_tools_source",
    "skip_workflows",
    "only_workflows",
    "github_release",
    "python",
    "npm",
    "go",
    "docker",
)
_CI_PYTHON_KEYS = (
    "test_versions",
    "lint",
    "format_check",
    "install",
    "test_command",
    "setup_steps",
    "extra_steps",
    "projects",
    "pypi_environment",
    "publish_requires_tests",
    "verify_tag_version",
    "publish_projects",
    "skip_if_published",
)
_CI_NPM_KEYS = (
    "node_version",
    "lint",
    "build",
    "cache",
    "npm_environment",
    "use_provenance",
    "use_oidc",
    "publish_requires_tests",
    "publish_projects",
    "skip_if_published",
)
_CI_GO_KEYS = (
    "go_version",
    "lint",
    "golangci_version",
    "enable_govulncheck",
    "test_args",
    "coverage",
    "module_tags",
    "govulncheck_version",
    "govulncheck_ignore",
)
_CI_DOCKER_KEYS = (
    "default_platforms",
    "platform_runners",
    "build_on_pr",
    "enable_workflow_dispatch_version",
    "test_prereqs",
)

_CI_PYTHON_LINT_CHOICES = {"ruff", "none"}
_CI_NPM_LINT_CHOICES = {"tsc-noemit", "eslint", "none"}
_CI_GO_LINT_CHOICES = {"golangci-lint", "none"}
_CI_GO_MODULE_TAG_MODES = {"none", "verify", "push"}
_DOCKER_TAG_STYLES = {"standard", "dev"}
_DOCKER_BUILD_STRATEGIES = {"auto", "qemu", "native"}
_DOCKER_TEST_PREREQ_CHOICES = {"python", "npm", "go"}


def _parse_publish_projects(
    raw: Any,
    project_versions: Mapping[str, str],
    where: str,
) -> tuple:
    """Validate a publish allowlist against the declared project names.

    Only checks that each name is a known project; whether it is a project of
    the *right language* is checked by the workflow builder, which is where the
    per-language manifest map lives. A typo here would otherwise silently
    allowlist nothing and drop every publish job.
    """
    if not isinstance(raw, list):
        raise ConfigError(f"{where}: expected list of project names")
    names = tuple(str(p) for p in raw)
    unknown = sorted({p for p in names if p not in project_versions})
    if unknown:
        raise ConfigError(
            f"{where}: unknown project(s) {unknown}; "
            f"expected one of {sorted(project_versions)}"
        )
    return names


_CI_STEP_KEYS = ("name", "run", "if", "working_directory")
_CI_PYTHON_PROJECT_KEYS = ("install", "test_command", "setup_steps", "extra_steps")


def _parse_ci_steps(raw: Any, where: str) -> tuple:
    """Parse a list of injected steps."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{where}: expected list of steps")
    steps: List[CiStep] = []
    for idx, entry in enumerate(raw):
        at = f"{where}[{idx}]"
        block = _expect_mapping(entry, at)
        _reject_unknown(block, _CI_STEP_KEYS, at)
        name = block.get("name")
        run = block.get("run")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{at}.name: required non-empty string")
        if not isinstance(run, str) or not run.strip():
            raise ConfigError(f"{at}.run: required non-empty shell command")
        if_expr = block.get("if")
        wd = block.get("working_directory")
        if if_expr is not None and not isinstance(if_expr, str):
            raise ConfigError(f"{at}.if: expected string expression")
        if wd is not None and (not isinstance(wd, str) or not wd.strip()):
            raise ConfigError(f"{at}.working_directory: expected non-empty string")
        steps.append(
            CiStep(
                name=name.strip(),
                run=run.rstrip("\n"),
                if_expr=if_expr,
                working_directory=wd.strip() if isinstance(wd, str) else None,
            )
        )
    return tuple(steps)


def _parse_ci_python_projects(
    raw: Any,
    project_versions: Mapping[str, str],
    where: str,
) -> Dict[str, CiPythonProject]:
    block = _expect_mapping(raw, where)
    out: Dict[str, CiPythonProject] = {}
    for name, entry in block.items():
        project = str(name)
        at = f"{where}.{project}"
        if project not in project_versions:
            raise ConfigError(
                f"{at}: unknown project; expected one of {sorted(project_versions)}"
            )
        sub = _expect_mapping(entry, at)
        _reject_unknown(sub, _CI_PYTHON_PROJECT_KEYS, at)
        out[project] = CiPythonProject(
            install=str(sub["install"]) if "install" in sub else None,
            test_command=str(sub["test_command"]) if "test_command" in sub else None,
            setup_steps=_parse_ci_steps(sub.get("setup_steps"), f"{at}.setup_steps"),
            extra_steps=_parse_ci_steps(sub.get("extra_steps"), f"{at}.extra_steps"),
        )
    return out


def _parse_ci_python(raw: Any, project_versions: Mapping[str, str]) -> CiPythonConfig:
    if raw is None:
        return CiPythonConfig()
    block = _expect_mapping(raw, "ci.python")
    _reject_unknown(block, _CI_PYTHON_KEYS, "ci.python")
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
    if "format_check" in block:
        kwargs["format_check"] = _expect_bool(block, "format_check", "ci.python", False)
    if "install" in block:
        kwargs["install"] = str(block["install"])
    if "test_command" in block:
        kwargs["test_command"] = str(block["test_command"])
    if "setup_steps" in block:
        kwargs["setup_steps"] = _parse_ci_steps(
            block["setup_steps"], "ci.python.setup_steps"
        )
    if "extra_steps" in block:
        kwargs["extra_steps"] = _parse_ci_steps(
            block["extra_steps"], "ci.python.extra_steps"
        )
    if "projects" in block:
        kwargs["projects"] = _parse_ci_python_projects(
            block["projects"], project_versions, "ci.python.projects"
        )
    if "pypi_environment" in block:
        kwargs["pypi_environment"] = str(block["pypi_environment"])
    if "publish_requires_tests" in block:
        kwargs["publish_requires_tests"] = _expect_bool(block, "publish_requires_tests", "ci.python", False)
    if "verify_tag_version" in block and block["verify_tag_version"] is not None:
        project = str(block["verify_tag_version"])
        if project not in project_versions:
            raise ConfigError(
                f"ci.python.verify_tag_version: '{project}' is not a known "
                "project in versions.yaml"
            )
        kwargs["verify_tag_version"] = project
    if "publish_projects" in block:
        kwargs["publish_projects"] = _parse_publish_projects(
            block["publish_projects"], project_versions, "ci.python.publish_projects"
        )
    if "skip_if_published" in block:
        kwargs["skip_if_published"] = _expect_bool(
            block, "skip_if_published", "ci.python", False
        )
    return CiPythonConfig(**kwargs)


def _parse_ci_npm(raw: Any, project_versions: Mapping[str, str]) -> CiNpmConfig:
    if raw is None:
        return CiNpmConfig()
    block = _expect_mapping(raw, "ci.npm")
    _reject_unknown(block, _CI_NPM_KEYS, "ci.npm")
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
    if "build" in block:
        kwargs["build"] = _expect_bool(block, "build", "ci.npm", False)
    if "cache" in block:
        kwargs["cache"] = _expect_bool(block, "cache", "ci.npm", False)
    if "npm_environment" in block:
        kwargs["npm_environment"] = str(block["npm_environment"])
    if "use_provenance" in block:
        kwargs["use_provenance"] = _expect_bool(block, "use_provenance", "ci.npm", False)
    if "use_oidc" in block:
        kwargs["use_oidc"] = _expect_bool(block, "use_oidc", "ci.npm", False)
    if "publish_requires_tests" in block:
        kwargs["publish_requires_tests"] = _expect_bool(
            block, "publish_requires_tests", "ci.npm", True
        )
    if "publish_projects" in block:
        kwargs["publish_projects"] = _parse_publish_projects(
            block["publish_projects"], project_versions, "ci.npm.publish_projects"
        )
    if "skip_if_published" in block:
        kwargs["skip_if_published"] = _expect_bool(
            block, "skip_if_published", "ci.npm", False
        )
    return CiNpmConfig(**kwargs)


def _parse_ci_go(raw: Any) -> CiGoConfig:
    if raw is None:
        return CiGoConfig()
    block = _expect_mapping(raw, "ci.go")
    _reject_unknown(block, _CI_GO_KEYS, "ci.go")
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
        kwargs["enable_govulncheck"] = _expect_bool(block, "enable_govulncheck", "ci.go", False)
    if "test_args" in block:
        kwargs["test_args"] = str(block["test_args"])
    if "coverage" in block:
        kwargs["coverage"] = _expect_bool(block, "coverage", "ci.go", False)
    if "govulncheck_version" in block:
        kwargs["govulncheck_version"] = str(block["govulncheck_version"])
    if "govulncheck_ignore" in block:
        raw_ignore = block["govulncheck_ignore"]
        if not isinstance(raw_ignore, list):
            raise ConfigError(
                "ci.go.govulncheck_ignore: expected a list of {id, reason} mappings"
            )
        entries = []
        for item in raw_ignore:
            entry = _expect_mapping(item, "ci.go.govulncheck_ignore[]")
            _reject_unknown(entry, ("id", "reason", "projects"), "ci.go.govulncheck_ignore[]")
            vid = str(entry.get("id", "")).strip()
            reason = str(entry.get("reason", "")).strip()
            if not vid:
                raise ConfigError("ci.go.govulncheck_ignore[].id: required")
            if not reason:
                raise ConfigError(
                    f"ci.go.govulncheck_ignore[{vid}].reason: required — an "
                    "allow-listed advisory must record why it is accepted"
                )
            raw_projects = entry.get("projects")
            projects: tuple = ()
            if raw_projects is not None:
                if not isinstance(raw_projects, list) or not raw_projects:
                    raise ConfigError(
                        f"ci.go.govulncheck_ignore[{vid}].projects: expected a "
                        "non-empty list of project names"
                    )
                projects = tuple(str(x) for x in raw_projects)
            entries.append(GovulncheckIgnore(vid, reason, projects))
        kwargs["govulncheck_ignore"] = tuple(entries)
    if "module_tags" in block:
        mode = str(block["module_tags"])
        if mode not in _CI_GO_MODULE_TAG_MODES:
            raise ConfigError(
                f"ci.go.module_tags: expected one of "
                f"{sorted(_CI_GO_MODULE_TAG_MODES)}, got '{mode}'"
            )
        kwargs["module_tags"] = mode
    return CiGoConfig(**kwargs)


def _parse_ci_docker(raw: Any) -> CiDockerConfig:
    if raw is None:
        return CiDockerConfig()
    block = _expect_mapping(raw, "ci.docker")
    _reject_unknown(block, _CI_DOCKER_KEYS, "ci.docker")
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
        kwargs["build_on_pr"] = _expect_bool(block, "build_on_pr", "ci.docker", False)
    if "enable_workflow_dispatch_version" in block:
        kwargs["enable_workflow_dispatch_version"] = _expect_bool(
            block, "enable_workflow_dispatch_version", "ci.docker", True
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


def _parse_ci(raw: Any, project_versions: Mapping[str, str]) -> CiConfig:
    if raw is None:
        return CiConfig()
    block = _expect_mapping(raw, "ci")
    _reject_unknown(block, _CI_KEYS, "ci")
    kwargs: Dict[str, Any] = {}

    if "bootstrap_method" in block:
        method = str(block["bootstrap_method"])
        if method not in _CI_BOOTSTRAP_METHODS:
            raise ConfigError(
                f"ci.bootstrap_method: expected one of "
                f"{sorted(_CI_BOOTSTRAP_METHODS)}, got '{method}'"
            )
        kwargs["bootstrap_method"] = method
    if "repo_tools_source" in block:
        source = str(block["repo_tools_source"]).strip()
        if not source:
            raise ConfigError("ci.repo_tools_source: expected non-empty source spec")
        if "'" in source:
            raise ConfigError(
                "ci.repo_tools_source: single quotes are not allowed; the value "
                "is embedded in a single-quoted shell argument"
            )
        kwargs["repo_tools_source"] = source
    if "test_branches" in block:
        branches = block["test_branches"]
        if not isinstance(branches, list) or not branches:
            raise ConfigError("ci.test_branches: expected non-empty list of branch names")
        kwargs["test_branches"] = tuple(str(b) for b in branches)
    if "push_branches" in block:
        pb = block["push_branches"]
        if not isinstance(pb, list) or not pb:
            raise ConfigError("ci.push_branches: expected non-empty list of branch names")
        kwargs["push_branches"] = tuple(str(b) for b in pb)
    if "skip_workflows" in block:
        skip = block["skip_workflows"]
        if not isinstance(skip, list):
            raise ConfigError(
                "ci.skip_workflows: expected list of workflow basenames (no .yml)"
            )
        kwargs["skip_workflows"] = tuple(str(s) for s in skip)
    if "github_release" in block:
        kwargs["github_release"] = _expect_bool(block, "github_release", "ci", False)
    if "only_workflows" in block:
        only = block["only_workflows"]
        if not isinstance(only, list):
            raise ConfigError(
                "ci.only_workflows: expected list of workflow basenames (no .yml)"
            )
        kwargs["only_workflows"] = tuple(str(s) for s in only)
    if "python" in block:
        kwargs["python"] = _parse_ci_python(block["python"], project_versions)
    if "npm" in block:
        kwargs["npm"] = _parse_ci_npm(block["npm"], project_versions)
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
    if "image_name" in block and block["image_name"] is not None:
        img_name = block["image_name"]
        if not isinstance(img_name, str) or not img_name.strip():
            raise ConfigError(
                f"docker.images.{name}.image_name: expected non-empty string"
            )
        kwargs["image_name"] = img_name.strip()
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


_PROTO_TOOLCHAIN_KEYS = (
    "protoc",
    "protoc_gen_go",
    "protoc_gen_go_grpc",
    "grpcio_tools",
    "proto_loader",
)
# Go module pins get `v`-normalized so they can be passed to `go install pkg@ver`.
_PROTO_GO_MODULE_PINS = ("protoc_gen_go", "protoc_gen_go_grpc")
_PROTO_TS_GENERATORS = {"proto-loader", "ts-proto", "protoc-gen-ts"}
_PROTO_GO_PATHS_MODES = {"source_relative", "import"}
_PROTO_KEYS = ("dir", "files", "toolchain", "outputs")
_PROTO_OUTPUT_KEYS = {
    "go": ("path", "paths", "grpc", "gofmt"),
    "python": ("path", "stubs", "grpc", "fix_relative_imports", "ensure_init_py"),
    "typescript": ("path", "generator", "grpc_lib", "package_dir", "options"),
}




def _proto_version(block: Mapping[str, Any], key: str, where: str) -> Optional[str]:
    if key not in block or block[key] is None:
        return None
    val = block[key]
    if not isinstance(val, (str, int, float)):
        raise ConfigError(f"{where}.{key}: expected version string")
    text = str(val).strip()
    if not text:
        raise ConfigError(f"{where}.{key}: expected non-empty version string")
    return text


def _parse_proto_toolchain(raw: Any, preferred: PreferredVersions) -> ProtoToolchainConfig:
    block = _expect_mapping(raw, "proto.toolchain")
    _reject_unknown(block, _PROTO_TOOLCHAIN_KEYS, "proto.toolchain")

    kwargs: Dict[str, Any] = {}
    for key in _PROTO_TOOLCHAIN_KEYS:
        val = _proto_version(block, key, "proto.toolchain")
        if val is not None:
            kwargs[key] = val

    # `protoc_gen_go: null` (or absent) derives from the go module pin, since
    # protoc-gen-go ships *from* google.golang.org/protobuf. Keeping one source
    # of truth beats restating a version that go.mod already governs.
    if kwargs.get("protoc_gen_go") is None:
        derived = preferred.for_language("go").get("google.golang.org/protobuf")
        if derived is not None and str(derived).strip():
            kwargs["protoc_gen_go"] = str(derived).strip()

    for key in _PROTO_GO_MODULE_PINS:
        if kwargs.get(key) is not None:
            kwargs[key] = normalize_go(kwargs[key])

    return ProtoToolchainConfig(**kwargs)


def _expect_bool(block: Mapping[str, Any], key: str, where: str, default: bool) -> bool:
    """Read a strictly-boolean key.

    `bool(value)` would coerce anything truthy, which is actively dangerous for
    a flag: quoted `coverage: "no"` is the string "no", and `bool("no")` is
    True — silently the opposite of what the author wrote.
    """
    if key not in block:
        return default
    val = block[key]
    if not isinstance(val, bool):
        raise ConfigError(f"{where}.{key}: expected boolean, got {type(val).__name__}")
    return val


def _proto_out_path(block: Mapping[str, Any], where: str) -> str:
    path = block.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ConfigError(f"{where}.path: required string (output directory)")
    return path.strip()


def _parse_proto_outputs(raw: Any) -> Dict[str, Any]:
    block = _expect_mapping(raw, "proto.outputs")
    _reject_unknown(block, _PROTO_OUTPUT_KEYS.keys(), "proto.outputs")

    out: Dict[str, Any] = {}

    if "go" in block:
        go_block = _expect_mapping(block["go"], "proto.outputs.go")
        _reject_unknown(go_block, _PROTO_OUTPUT_KEYS["go"], "proto.outputs.go")
        paths_mode = str(go_block.get("paths", "source_relative"))
        if paths_mode not in _PROTO_GO_PATHS_MODES:
            raise ConfigError(
                f"proto.outputs.go.paths: expected one of "
                f"{sorted(_PROTO_GO_PATHS_MODES)}, got '{paths_mode}'"
            )
        out["go"] = ProtoGoOutput(
            path=_proto_out_path(go_block, "proto.outputs.go"),
            paths=paths_mode,
            grpc=_expect_bool(go_block, "grpc", "proto.outputs.go", True),
            gofmt=_expect_bool(go_block, "gofmt", "proto.outputs.go", True),
        )

    if "python" in block:
        py_block = _expect_mapping(block["python"], "proto.outputs.python")
        _reject_unknown(py_block, _PROTO_OUTPUT_KEYS["python"], "proto.outputs.python")
        out["python"] = ProtoPythonOutput(
            path=_proto_out_path(py_block, "proto.outputs.python"),
            stubs=_expect_bool(py_block, "stubs", "proto.outputs.python", True),
            grpc=_expect_bool(py_block, "grpc", "proto.outputs.python", True),
            fix_relative_imports=_expect_bool(
                py_block, "fix_relative_imports", "proto.outputs.python", True
            ),
            ensure_init_py=_expect_bool(
                py_block, "ensure_init_py", "proto.outputs.python", True
            ),
        )

    if "typescript" in block:
        ts_block = _expect_mapping(block["typescript"], "proto.outputs.typescript")
        _reject_unknown(
            ts_block, _PROTO_OUTPUT_KEYS["typescript"], "proto.outputs.typescript"
        )
        generator = str(ts_block.get("generator", "proto-loader"))
        if generator not in _PROTO_TS_GENERATORS:
            raise ConfigError(
                f"proto.outputs.typescript.generator: expected one of "
                f"{sorted(_PROTO_TS_GENERATORS)}, got '{generator}'"
            )
        options_raw = ts_block.get("options")
        kwargs: Dict[str, Any] = {}
        if options_raw is not None:
            if not isinstance(options_raw, list):
                raise ConfigError(
                    "proto.outputs.typescript.options: expected list of CLI flags"
                )
            kwargs["options"] = tuple(str(o) for o in options_raw)
        pkg_dir = ts_block.get("package_dir")
        if pkg_dir is not None:
            if not isinstance(pkg_dir, str) or not pkg_dir.strip():
                raise ConfigError(
                    "proto.outputs.typescript.package_dir: expected non-empty string"
                )
            kwargs["package_dir"] = pkg_dir.strip()
        out["typescript"] = ProtoTypeScriptOutput(
            path=_proto_out_path(ts_block, "proto.outputs.typescript"),
            generator=generator,
            grpc_lib=str(ts_block.get("grpc_lib", "@grpc/grpc-js")),
            **kwargs,
        )

    return out


def _parse_proto(raw: Any, preferred: PreferredVersions) -> ProtoConfig:
    if raw is None:
        return ProtoConfig()
    block = _expect_mapping(raw, "proto")
    _reject_unknown(block, _PROTO_KEYS, "proto")

    proto_dir = block.get("dir")
    if not isinstance(proto_dir, str) or not proto_dir.strip():
        raise ConfigError("proto.dir: required string (directory containing .proto files)")

    files_raw = block.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise ConfigError("proto.files: expected non-empty list of .proto filenames")
    files = tuple(str(f).strip() for f in files_raw)
    if any(not f for f in files):
        raise ConfigError("proto.files: entries must be non-empty filenames")
    bad_ext = [f for f in files if not f.endswith(".proto")]
    if bad_ext:
        raise ConfigError(f"proto.files: entries must end in '.proto', got {bad_ext}")
    dupes = sorted({f for f in files if files.count(f) > 1})
    if dupes:
        raise ConfigError(f"proto.files: duplicate entries {dupes}")

    outputs = _parse_proto_outputs(block.get("outputs"))
    if not outputs:
        raise ConfigError(
            "proto.outputs: at least one of 'go', 'python', 'typescript' is required"
        )

    return ProtoConfig(
        dir=proto_dir.strip(),
        files=files,
        toolchain=_parse_proto_toolchain(block.get("toolchain"), preferred),
        **outputs,
    )


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
    ci = _parse_ci(data.get("ci"), project_versions)
    docker = _parse_docker(data.get("docker"), project_versions)
    proto = _parse_proto(data.get("proto"), preferred)

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
        proto=proto,
    )


__all__ = [
    "ConfigError",
    "ProjectRule",
    "PreferredVersions",
    "DependencyMappings",
    "SourcesConfig",
    "GoToolchainConfig",
    "CiStep",
    "CiPythonProject",
    "CiPythonConfig",
    "CiNpmConfig",
    "GovulncheckIgnore",
    "CiGoConfig",
    "CiDockerConfig",
    "CiConfig",
    "DockerImage",
    "DockerConfig",
    "ProtoToolchainConfig",
    "ProtoGoOutput",
    "ProtoPythonOutput",
    "ProtoTypeScriptOutput",
    "ProtoConfig",
    "SyncConfig",
    "load_config",
    "RESERVED_KEYS",
]
