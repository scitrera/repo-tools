# scitrera-repo-tools

Monorepo maintenance toolkit. The primary subcommand, `sync-versions`, is
driven by `versions.yaml`; auxiliary subcommands (`npm-audit`, `missing-deps`,
`directory-split`) reuse the same config or stand alone.

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

Generates GitHub Actions workflows from `versions.yaml`. Produces up to seven
files in `.github/workflows/` depending on which languages and image
descriptors are present:

| File | Trigger | Purpose |
|---|---|---|
| `version-check.yml` | PR (paths-filtered) | Fail PRs that drift from `versions.yaml` |
| `test-python.yml` | push/PR to `test_branches` | Matrix test across Python versions, per project |
| `test-npm.yml` | push/PR to `test_branches` | Per-TS-project install + type-check + `npm test` |
| `test-go.yml` | push/PR to `test_branches` | `go vet` + race-test + optional golangci-lint / govulncheck per Go project |
| `publish-python.yml` | tag `v*.*.*` push | Per-project PyPI publish in dependency order |
| `publish-npm.yml` | tag `v*.*.*` push | Per-project npm publish in dependency order |
| `build-docker.yml` | tag `v*.*.*` push + dispatch | Cascaded multi-arch image builds with inline test prereqs |

The publish workflows respect the DAG defined by
`dependency_mappings.<lang>.dependencies` — every consumer's job declares
`needs: [publish-<dep>, ...]` so internal deps publish first. Both publish
workflows run `sync-versions --release` inline to rewrite local refs
(`workspace:`, `file:`, `git+...`, PEP 508 direct refs) into version pins
before building, so published artifacts are installable from PyPI/npm
without the original repo checkout.

### Behavior

```bash
generate-ci-gha             # write missing files; show unified diff for drift; exit 1 on drift
generate-ci-gha --force     # overwrite drift
generate-ci-gha --check     # never write; CI-friendly drift detector
```

Default (no flags) creates files on first run in a fresh repo, and acts as
a drift check on subsequent runs — safe to wire into CI.

### `ci:` block in `versions.yaml`

All keys optional; sensible defaults applied for anything you omit.

```yaml
ci:
  test_branches: [main, develop]              # default: [main, develop]
  skip_workflows: []                          # workflow basenames (no .yml) to leave unmanaged
  python:
    test_versions: ["3.11", "3.12", "3.13"]   # default
    lint: ruff                                  # ruff | none; default: ruff
    install: 'pip install -e ".[test]"'         # default
    pypi_environment: pypi                      # GitHub environment, default: pypi
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

**Skipping a workflow.** If you hand-customize a generated file and want
the generator to stop managing it, add its basename to `ci.skip_workflows`:

```yaml
ci:
  skip_workflows: [build-docker]   # leave .github/workflows/build-docker.yml alone
```

The on-disk file is never touched and no drift is reported for skipped
entries — handy when one workflow needs bespoke logic but you still want
the others auto-synced.

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
