# scitrera-repo-tools

Monorepo maintenance toolkit. The primary subcommand, `sync-versions`, is
driven by `versions.yaml`; further subcommands (`generate-ci-gha`,
`compile-protos`, `npm-audit`, `missing-deps`, `directory-split`) reuse the same
config or stand alone.

## Install

```bash
pip install scitrera-repo-tools
# or, from source:
pip install -e .
```

Every subcommand is available either as a top-level console script or via the
`repo-tools` dispatcher:

```bash
sync-versions ...
repo-tools sync-versions ...
python -m scitrera_repo_tools sync-versions ...
```

Drop-in shims live in `scripts/` (`update-versions.py`, `npm-audit.py`,
`missing-deps.py`, `directory-split.py`). Copy any of them into a target repo
and they will use the installed package if available, otherwise fall back to
`uvx` and finally print install instructions.

## `sync-versions`

From any directory inside a monorepo containing a `versions.yaml`:

```bash
sync-versions            # apply updates (preserves local refs)
sync-versions --check    # dry-run, exit 1 on drift
sync-versions --verbose  # show every file inspected
sync-versions --config path/to/versions.yaml
```

### Release mode

By default, `sync-versions` preserves local-reference dep specifiers
(`file:../foo`, `workspace:*`, `link:`, `git+...`, PEP 508 `pkg @ git+...`)
so local development keeps working. Before publishing to PyPI/npm, opt in
to rewrite those into canonical version pins from `versions.yaml`:

```bash
sync-versions --release            # rewrite local refs to version pins
sync-versions --release --check    # preview the release-pass diff in CI
```

Typical pre-publish flow:

```bash
sync-versions --release
git diff                            # review the version-pin substitutions
# ... build + publish (npm publish / uv publish) ...
git checkout -- .                   # restore local refs for ongoing dev
```

## `versions.yaml` schema

```yaml
# Top-level project versions
my-python-pkg: 0.1.22
my-ts-pkg: 0.1.22

# External dep pins per language (optional)
preferred_versions:
  python:
    "pydantic": "2.13.4"             # bare -> `==2.13.4`; literal w/ operator preserved
  typescript:
    "@modelcontextprotocol/sdk": "^1.26.0"
  go:
    "google.golang.org/grpc": "v1.65.0"      # bare or `v`-prefixed both accepted
    "google.golang.org/protobuf": "1.34.1"

# Per-project file rules (replaces the hardcoded PROJECT_RULES dict)
project_rules:
  my-python-pkg:
    - { type: pyproject, path: my-python-pkg/pyproject.toml }
    - { type: init_py,   path: my-python-pkg/src/my_pkg/__init__.py }
  my-ts-pkg:
    - { type: package,   path: my-ts-pkg/package.json }

# Internal monorepo cross-reference sync (optional)
dependency_mappings:
  python:
    packages:
      "my-internal-dir": "my-published-name"
    dependencies:
      my-consumer:
        - "my-internal-dir"

# Lockfile fallback for nulls in preferred_versions (optional)
sources:
  python:
    - "uv.lock"

# Global Go toolchain directives (optional, no-inject)
# Walks every go.mod referenced in project_rules.gomod_require.
go_toolchain:
  go:        "1.25"      # rewrites the `go X.Y` directive
  toolchain: "1.25.10"   # rewrites `toolchain goX.Y.Z` (Go 1.21+ feature)
```

## `compile-protos`

Compiles `.proto` files for Go, Python and TypeScript from a single `proto:`
block, after verifying that the installed toolchain matches the pins in
`proto.toolchain`.

```bash
compile-protos                     # regenerate; write anything missing or stale
compile-protos --check             # write nothing; exit 1 on drift (CI-friendly)
compile-protos --lang go           # restrict to one output language (repeatable)
compile-protos --python .venv/bin/python   # interpreter for grpc_tools.protoc
compile-protos --skip-verify       # bypass pin verification (expect drift)
```

### Why the pins are the point

Generated protobuf artifacts embed the versions of the tools that produced them
(`// protoc v5.27.1`, `# Protobuf Python Version: 6.31.1`). An unpinned compiler
therefore turns any byte-equality check into a coin flip: CI installs a
different `protoc` than a developer has, regenerates, and reports drift in files
nobody edited. `compile-protos` verifies every required tool *before* generating
anything and fails with the exact install command, so a mismatch surfaces
locally instead of as a confusing CI diff.

Note that `protoc` and `grpcio-tools` are two **independent** compilers —
`grpc_tools` bundles its own libprotoc — so a repo can easily end up with Go
artifacts stamped by one and Python artifacts stamped by another. The bundled
protoc is cross-checked (major version) against the `protoc` pin to catch
exactly that.

### `proto:` block in `versions.yaml`

Inputs, toolchain pins and outputs live in one block on purpose: pins kept apart
from the code that consumes them are how a pin silently becomes inert.

```yaml
proto:
  # ── inputs ──
  dir: api/proto                                       # required
  files: [aether.proto, sandbox_relay_tunnel.proto]    # required, non-empty

  # ── toolchain: exact pins, verified before codegen ──
  toolchain:
    protoc: "31.1"               # standalone protoc (Go path). Use an exact
                                 # version, never a floating range like 27.x
    protoc_gen_go: null          # null/omitted → derived from
                                 # preferred_versions.go["google.golang.org/protobuf"],
                                 # since protoc-gen-go ships from that module
    protoc_gen_go_grpc: "v1.6.2" # SEPARATE nested module — NOT derivable from
                                 # google.golang.org/grpc
    grpcio_tools: "1.76.0"
    proto_loader: "0.8.1"

  # ── outputs: at least one required; a language is enabled by its presence ──
  outputs:
    go:
      path: api/proto
      paths: source_relative     # source_relative | import
      grpc: true                 # also run protoc-gen-go-grpc
      gofmt: true
    python:
      path: sdk/python-client/scitrera_aether_client/proto
      stubs: true                # --pyi_out
      grpc: true
      fix_relative_imports: true # rewrite bare sibling `import foo_pb2`
      ensure_init_py: true       # only when the file is absent
    typescript:
      path: sdk/typescript/src/proto
      generator: proto-loader    # proto-loader | ts-proto | protoc-gen-ts
      grpc_lib: "@grpc/grpc-js"
      package_dir: sdk/typescript  # npm root holding node_modules/.bin;
                                   # discovered from `path` when omitted
      options: [--longs=String, --enums=String, --defaults, --oneofs, --includeComments]
```

The two Go plugin pins are normalized to Go's `v`-prefixed module form, so
either `1.6.2` or `v1.6.2` is accepted and both render as `v1.6.2`.

Unknown keys are rejected at every level of this block — stricter than the older
blocks in `versions.yaml`, and deliberately so. The whole purpose here is to stop
a pin from quietly doing nothing, so a typo must be an error, not a no-op.

`fix_relative_imports` solves a universal protobuf-Python problem, not a project
quirk: generated `_pb2_grpc.py` and cross-importing `_pb2.py` modules reference
siblings as `import foo_pb2`, which breaks once the generated code lives inside
a package.

### Behavior

Codegen always runs into a temporary mirror of the repo layout first; the result
is then either compared (`--check`) or copied into place. Consequences worth
relying on:

- **Untracked files are caught.** `--check` enumerates the *generated* set, so a
  generated file that was never committed reports as `missing`. A `git diff`
  based check cannot see it — untracked files don't appear in a diff — which is a
  common way generated code goes absent from a commit while CI stays green.
- **Post-processing is scoped.** gofmt and import rewrites only ever touch
  freshly generated files, so checked-in sources sharing an output directory are
  never reformatted.
- **Failures are atomic.** A codegen error leaves the working tree untouched.
- `ensure_init_py` creates `__init__.py` only when the real tree lacks one, so an
  existing package initializer with content is never clobbered.

Only `proto-loader` is wired up for TypeScript today. The other generators are
accepted by the schema — their output shapes differ fundamentally, so the choice
belongs in config from the start — and the runner reports them as unimplemented
rather than failing obscurely.

## `npm-audit`

Runs `npm audit` (and optionally `npm audit fix`) across every TypeScript
package declared in `versions.yaml` (i.e. every `project_rules` entry with a
`type: package` rule). Mirrors the bash convention of bailing on missing
lockfiles, auto-running `npm ci` when `node_modules` is absent, and returning
a non-zero exit on any audit failure.

```bash
npm-audit                          # audit every TS project
npm-audit --fix                    # non-breaking fix + audit
npm-audit --fix --force            # include breaking fixes
npm-audit --level high             # high + critical only
npm-audit my-ts-pkg another-ts-pkg # subset by versions.yaml project name
```

## `missing-deps`

Reads `pyproject.toml` and prints declared dependencies that are not yet
installed in the current environment. Useful for piping into a selective
`pip install` without re-resolving the full graph.

```bash
missing-deps                       # print missing deps from [project].dependencies
missing-deps --extra test          # also include the `[test]` extra
missing-deps --ignore some-pkg     # skip specific packages
missing-deps --print-installed     # report installed versions to stderr
```

## `directory-split`

Splits a directory into N approximately-equal buckets via greedy bin-packing.
Top-level entries are treated as atomic units; top-level *directories* go one
level deeper so their children can spread across buckets (preventing one large
dir from dominating). Output: `<parent>/<basename>-1` … `<parent>/<basename>-N`.
Deterministic for fixed inputs.

```bash
directory-split ./data 4                       # split into 4 buckets
directory-split ./data 4 --exclude "*.log"     # skip log files at top level
directory-split ./data 4 --exclude .git --exclude node_modules
```

## `generate-ci-gha`

Generates GitHub Actions workflows from `versions.yaml`. Produces up to eight
files in `.github/workflows/` depending on which languages, proto outputs and
image descriptors are present:

| File | Trigger | Purpose |
|---|---|---|
| `version-check.yml` | PR (paths-filtered) | Fail PRs that drift from `versions.yaml` |
| `proto-check.yml` | PR (paths-filtered) | Fail PRs whose generated proto code is stale, one job per language |
| `test-python.yml` | push/PR to `test_branches` | Matrix test across Python versions, per project |
| `test-npm.yml` | push/PR to `test_branches` | Per-TS-project install + type-check + `npm test` |
| `test-go.yml` | push/PR to `test_branches` | `go vet` + race-test + optional golangci-lint / govulncheck per Go project |
| `publish-python.yml` | tag `v*.*.*` push | Per-project PyPI publish in dependency order |
| `publish-npm.yml` | tag `v*.*.*` push | Per-project npm publish in dependency order |
| `build-docker.yml` | tag `v*.*.*` push + dispatch | Cascaded multi-arch image builds with inline test prereqs |

`proto-check.yml` is emitted only when a `proto:` block is present, and gets one
job per configured output language (`--lang go` / `--lang python` /
`--lang typescript`). The split is deliberate: each job provisions just its own
toolchain — protoc plus the Go plugins, or grpcio-tools, or `npm ci` — so the
three run in parallel rather than serializing one job through every ecosystem's
installer. Every version comes from `proto.toolchain`, so the workflow and
`compile-protos` cannot disagree, and `compile-protos --check` re-verifies at
run time in case a setup action resolves to something else.

Because an unpinned compiler in CI defeats the purpose of the check, a `proto:`
block missing a pin its enabled outputs require is a **generation error** rather
than a silent default. Pin the tool, or add `proto-check` to `ci.skip_workflows`.

The publish workflows respect the DAG defined by
`dependency_mappings.<lang>.dependencies` — every consumer's job declares
`needs: [publish-<dep>, ...]` so internal deps publish first. Both publish
workflows run `sync-versions --release` inline to rewrite local refs
(`workspace:`, `file:`, `git+...`, PEP 508 direct refs) into version pins
before building, so published artifacts are installable from PyPI/npm
without the original repo checkout.

`publish-python.yml` additionally gates every upload on the test matrix
(`ci.python.publish_requires_tests`, on by default), because a tag push is
not revocable once it reaches PyPI. Two further gates are opt-in:
`ci.python.verify_tag_version` refuses to publish when the pushed tag
disagrees with `versions.yaml`, and `ci.github_release` attaches the
built distributions to a GitHub release.

### Bootstrapping repo-tools inside generated workflows

Generated workflows need `sync-versions` on the runner. By default they
install `uv` and resolve the tool on demand with
`uvx --from 'scitrera-repo-tools'` — the same resolution path the `scripts/`
shims use locally, so CI and developer machines behave alike.

`ci.repo_tools_source` controls *what* gets resolved, and accepts any uv/pip
source spec:

```yaml
ci:
  repo_tools_source: "scitrera-repo-tools==0.1.11"          # pinned PyPI release
  repo_tools_source: "git+https://github.com/scitrera/repo-tools.git@v0.1.11"
  repo_tools_source: "."                                     # the checked-out tree
```

Prefer a pinned spec. Tracking a moving branch means any push to that branch
can turn CI red in every repo that points at it, with no review gate and no
reproducible builds. `"."` is for the repo-tools repo itself, whose workflows
should exercise the commit under test rather than a previously published
artifact.

Set `ci.bootstrap_method: pip` for runners where uv is unavailable; the
generated steps fall back to `actions/setup-python` plus
`pip install <repo_tools_source>`.

### Behavior

```bash
generate-ci-gha             # write missing files; show unified diff for drift; exit 1 on drift
generate-ci-gha --force     # overwrite drift
generate-ci-gha --check     # never write; CI-friendly drift detector
```

Default (no flags) creates files on first run in a fresh repo, and acts as
a drift check on subsequent runs — safe to wire into CI.

### `ci:` block in `versions.yaml`

All keys optional; sensible defaults applied for anything you omit. Unknown keys
are rejected — in `ci:` and in each of `ci.python` / `ci.npm` / `ci.go` /
`ci.docker` — because a misspelled key reads as configuration that is being
honored while doing nothing at all.

This catches typos, not version skew: an *older* repo-tools cannot know about a
*newer* key and will silently ignore it. Pin `ci.repo_tools_source` when a
config depends on a recently added key.

```yaml
ci:
  test_branches: [main, develop]              # default: [main, develop]
  skip_workflows: []                          # workflow basenames (no .yml) to leave unmanaged
  only_workflows: []                          # allowlist; empty = manage everything that renders
  github_release: false                       # attach built dists to a GitHub release for the tag
  bootstrap_method: uvx                       # uvx | pip; default: uvx
  repo_tools_source: scitrera-repo-tools      # any uv/pip source spec; default: PyPI name
  python:
    test_versions: ["3.11", "3.12", "3.13"]   # default
    lint: ruff                                  # ruff | none; default: ruff
    install: 'pip install -e ".[test]"'         # default
    pypi_environment: pypi                      # GitHub environment, default: pypi
    publish_requires_tests: true                # gate PyPI upload on the test matrix; default: true
    verify_tag_version: null                    # project name; fail if tag != its versions.yaml version
  npm:
    node_version: "24"                          # default: "24"
    lint: tsc-noemit                            # tsc-noemit | eslint | none
    npm_environment: npm                        # default: npm
    use_provenance: false                       # add --provenance to npm publish
    use_oidc: false                             # skip NPM_TOKEN (trusted publisher)
  go:
    go_version: "1.25.10"                       # default: from go_toolchain.go, else "1.25"
    lint: golangci-lint                          # golangci-lint | none; default: golangci-lint
    golangci_version: "v2.11.4"
    enable_govulncheck: true                    # default: true
    test_args: "-race -count=1"
  docker:
    default_platforms: [linux/amd64, linux/arm64]
    platform_runners:                           # native runners; missing platforms fall back to QEMU
      linux/amd64: ubuntu-latest                # implicit; included by default
      linux/arm64: ubuntu-24.04-arm             # opt-in to native arm64 builds
    build_on_pr: false                          # also build (no push) on PRs
    enable_workflow_dispatch_version: true       # adds `version` input for redeploys
    test_prereqs: [python, npm, go]             # which test job sets inline ahead of builds
```

If a language has no `project_rules` entries (no `type: pyproject` /
`type: package` / `type: gomod_require` rules), its workflows are simply
not generated.

**Pinning the linter.** When `preferred_versions.python` declares a `ruff`
entry, the generated lint step installs that exact spec
(`pip install ruff==0.16.0`) instead of a floating `pip install ruff`. Pin it
— an unpinned linter turns an upstream release into a red build on an
unrelated PR. Note that pinning the *version* is only half the job: ruff's
default rule selection also changes across releases, so declare
`[tool.ruff.lint] select = [...]` in `pyproject.toml` as well.

**Dogfooding.** This repo's own `.github/workflows/` is generated by this
subcommand from its `versions.yaml`. Regenerate with
`python scripts/generate-ci-gha.py --force`.

**Skipping a workflow.** If you hand-customize a generated file and want
the generator to stop managing it, add its basename to `ci.skip_workflows`:

```yaml
ci:
  skip_workflows: [build-docker]   # leave .github/workflows/build-docker.yml alone
```

The on-disk file is never touched and no drift is reported for skipped
entries — handy when one workflow needs bespoke logic but you still want
the others auto-synced.

**Managing only some workflows.** `ci.only_workflows` is the inverse: an
allowlist naming the workflows the generator owns, leaving everything else
alone.

```yaml
ci:
  only_workflows: [proto-check]    # manage just this one; ignore the rest
```

Prefer this for incremental adoption. A repo taking on one generated workflow
at a time would otherwise have to enumerate every workflow it *doesn't* want in
`skip_workflows`, and revisit that list whenever a new generator is added.

Empty (the default) means "manage everything that renders". A name that isn't a
real workflow basename is an error, not an empty selection — a typo'd allowlist
would otherwise silently manage nothing and look like success. The two lists
compose: `only_workflows` selects, then `skip_workflows` subtracts.

### `docker:` block

Optional. Drives `build-docker.yml`. Omit if the repo doesn't build any
container images.

```yaml
docker:
  ghcr: scitrera                              # optional: ghcr.io/scitrera/<image>
  dockerhub: scitrera                          # optional: scitrera/<image> (requires DOCKERHUB_USERNAME/_TOKEN secrets)
  images:
    aether:
      context: .
      dockerfile: server/Dockerfile
      tag_style: standard                      # standard | dev; default: standard
      version_from: aether-gateway             # use versions.yaml[aether-gateway] for image tag
      build_strategy: auto                     # auto | qemu | native; default: auto
    aetherlite:
      context: server
      dockerfile: server/Dockerfile.aetherlite-dev
      needs: aether                            # cascade: child gets BASE_IMAGE=<reg>/aether:<base-tag>
      version_from: aether-gateway
    aetherlite-dev:
      context: server
      dockerfile: server/Dockerfile.aetherlite-dev
      needs: aetherlite
      tag_style: dev                           # dev- prefixed tags; suppresses :latest
      version_from: aether-gateway
      # base_image_arg: BASE_IMAGE             # override the build-arg name (default: BASE_IMAGE)
```

**Cascade semantics.** When image B `needs: A`, B's build job depends on
A's build (or merge) job, and `BASE_IMAGE=<primary-registry>/A:<A's base-tag>`
is injected as a build-arg so B's Dockerfile picks up exactly the image A
just produced.

**Build strategy.** `auto` (the default) picks `native` when every platform
listed for the image has an entry in `ci.docker.platform_runners`; otherwise
it falls back to a single QEMU job. `qemu` and `native` force one path
explicitly. In `native` mode, the generator emits one job per platform
(builds + pushes by digest) followed by a `merge-<image>` job that creates
the multi-arch manifest with `docker buildx imagetools create`.

**Image version source.** When `version_from` references a `versions.yaml`
project, the build job reads that project's version (via
`sync-versions --print-version <project>`) and injects it as extra raw
tags. Without `version_from`, image tags come from the git tag's semver
value via `docker/metadata-action`. Both sources are overridable at
runtime by the `workflow_dispatch` `version` input.

## License

BSD 3-Clause.
