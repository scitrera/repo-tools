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
  my-go-cmd:
    - { type: gomod,      path: go.mod }               # module declaration for CI
    # Rewrites `const Version = "..."` or `var version = "..."` — the latter is
    # the shape a command declares so `-ldflags "-X main.version=..."` can
    # override it, and its baked default is what `go install` reports.
    - { type: go_version, path: cmd/my-tool/main.go }

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
# Walks every declared Go module — the `gomod` rule when present, otherwise the
# `gomod_require` fallback. `go` is a minimum, not a pin: `1.25` admits any
# 1.25.x and later, whereas `1.25.11` locks out every earlier patch release.
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

Generates GitHub Actions workflows from `versions.yaml`. Produces up to nine
files in `.github/workflows/` depending on which languages, proto outputs and
image descriptors are present:

| File | Trigger | Purpose |
|---|---|---|
| `version-check.yml` | PR (paths-filtered) | Fail PRs that drift from `versions.yaml` |
| `proto-check.yml` | PR (paths-filtered) | Fail PRs whose generated proto code is stale, one job per language |
| `test-python.yml` | push/PR to `test_branches` | Matrix test across Python versions, per project |
| `test-npm.yml` | push/PR to `test_branches` | Per-TS-project install + type-check + `npm test` |
| `test-go.yml` | push/PR to `test_branches` | `go vet` + race-test + optional golangci-lint / govulncheck per Go project |
| `publish-go.yml` | tag `v*.*.*` push | Reconcile per-module Go tags; cross-compile release binaries; cut the GitHub release |
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

### `publish-go.yml` and Go module tags

Go has no publish step: a module version exists the moment `<dir>/vX.Y.Z` points
at a commit. `publish-go.yml` therefore makes the root `v*.*.*` tag the single
release signal — it gates on the Go tests, then reconciles the per-module tags
that Go actually resolves against. Module directories are derived from the
`gomod_require` rules already in `project_rules`, so there is nothing extra to
declare.

```yaml
ci:
  go:
    module_tags: verify     # none (default) | verify | push
```

`verify` fails the release when a module tag is missing or points at a different
commit than the release tag. `push` additionally creates and pushes the missing
ones, and requests `contents: write`. Start on `verify`; move to `push` once a
real release has proven the wiring.

Enabling it also turns on a consistency check that runs at generation time:
**a nested module's path must end with its own directory.** This is worth
understanding, because violating it fails quietly rather than loudly. Go locates
a nested module by directory, so a `server/go.mod` declaring
`module github.com/acme/thing` can never be fetched as `github.com/acme/thing`
(the proxy looks at the repo root) *nor* as `github.com/acme/thing/server` (the
declared path disagrees). Worse, if the repo root has no `go.mod`, the proxy
synthesizes a one-line module from it — so `go get github.com/acme/thing@v1.2.3`
resolves and downloads a phantom module carrying none of the real dependencies.
The check refuses to generate rather than emit a workflow that would bless that.

Because the root tag drives everything, submodule tags like `api/v1.2.3` do not
match the `v*.*.*` filters and trigger nothing — which is correct: they are the
artifact, not the cause.

### A GitHub release for a Go library

A single-module library has no nested tags to reconcile and no binaries to
build, so on the strength of the two halves above its release tag would trigger
nothing at all. `ci.github_release` covers that case too: the workflow gates on
the Go tests and cuts the release for the tag, attaching no files, because
there is no artifact — `go get` resolves the version from the proxy and the
release exists for its notes.

```yaml
ci:
  github_release: true
  go:
    verify_tag_version: my-lib     # project name; omit to skip the check
```

`verify_tag_version` is the Go counterpart of `ci.python.verify_tag_version`,
and it earns its keep more here: a Go module's version *is* its tag, so a tag
that disagrees with `versions.yaml` is not a mislabelled artifact you can
re-upload over — it is the released version, and the proxy exists to make
published versions immutable. The job runs `sync-versions --check` as well,
because `version-check.yml` only fires on pull requests. It gates the module-tag
reconciliation too, so a bad tag is caught before any `<dir>/vX.Y.Z` is pushed.

One release per tag: when the Python publish flow is also generating jobs, it
already attaches its distributions to that same release, so the Go side adds no
second release job. `ci.go.binaries` likewise brings its own release job, with
the built binaries attached.

### Release binaries (`ci.go.binaries`)

A Go repo whose artifact is a *command* has nothing to publish to a registry —
the release is the binary. `ci.go.binaries` cross-compiles each command across a
platform matrix on the `v*.*.*` tag and attaches the results to the GitHub
release:

```yaml
ci:
  github_release: true
  go:
    binaries:
      - name: mytool                       # published file name; also the job id
        package: ./cmd/mytool              # `go build` target, relative to the module
        # project: my-sdk-go               # required only with >1 Go module
        platforms: [ linux/amd64, linux/arm64, windows/amd64, windows/arm64, darwin/arm64 ]
        ldflags: "-s -w -X main.commit=$COMMIT"
        extra_files: [ LICENSE, README.md ]
    # Applies to any entry that declares no `platforms` of its own.
    binary_platforms: [ linux/amd64, linux/arm64, darwin/arm64 ]
```

Assets are named `<name>_<version>_<goos>_<goarch>`, packed as `.zip` for
Windows and `.tar.gz` elsewhere (`archive: tar.gz | zip | none` forces one), and
published alongside a `checksums.txt`. `<version>` is the pushed tag with any
leading `v` stripped; a `workflow_dispatch` run has no tag, so it builds
`0.0.0-dev.<short-sha>` rather than an asset with an empty version in its name.

`$VERSION` and `$COMMIT` are exported before `go build`, so `ldflags` can stamp
them without a second templating layer. The value is emitted inside a
double-quoted shell argument — which is what makes that expansion work — so a
double quote in it is rejected at config time rather than producing a build
command nobody wrote.

Every leg builds on `ubuntu-latest` with `CGO_ENABLED=0`, because Go
cross-compiles to all of these without a foreign toolchain and a per-OS runner
would buy queue time and nothing else. `env:` can override that, but a cgo build
also needs a runner that can link for the target, which this generator does not
provide.

Two behaviours are deliberate:

- **`fail-fast: false`.** One unsupported target must not withhold the assets
  for every platform that did build.
- **`if-no-files-found: error`.** A silently empty upload surfaces as a release
  that is merely *missing* a platform — which nobody notices until a user tries
  to download it.

Attaching to a release is gated on `ci.github_release`, the same switch the
Python side uses: whether a repo cuts GitHub releases is one decision, not one
per language. With it off the binaries are still built and uploaded as workflow
artifacts. In a repo that publishes both Python distributions *and* Go binaries
for one tag, the two workflows each attach their own files to that tag's
release.

`publish-go.yml` renders when *either* half applies, so a single-root-module
repo — which has no module tags to reconcile — still gets one for its binaries.

### Accepted-risk advisories (`govulncheck_ignore`)

govulncheck has no native suppression mechanism, so the generated security job
runs it with `-format json` and filters the findings itself:

```yaml
ci:
  go:
    govulncheck_ignore:
      - id: GO-2026-5668
        reason: "docker/docker; no upstream fix; tracked in SECURITY.md"
        projects: [my-sdk]        # optional; omit to apply to every Go module
```

Scope with `projects` when only some modules reach the vulnerable code. A
repo-wide waiver would otherwise make every *other* module report the entry as
stale on every run — training people to ignore the warning that keeps the list
from rotting. Naming a project that does not exist is an error rather than a
waiver that silently matches nothing.

`reason` is required — an allow-list entry is a security decision and the
workflow should record who accepted what. The reason is emitted as a comment
beside the id in the generated YAML.

This is deliberately narrower than marking the step `continue-on-error`, which
is the obvious shortcut and the wrong one: it suppresses *new* advisories too,
so the scan quietly stops being a control. Here only the reviewed ids are
waived, and anything else still fails the build.

Two further behaviours worth knowing:

- **Only reachable findings gate the build.** govulncheck also reports
  advisories that are merely present in the module graph but never called;
  those are not a vulnerability in the built binary and would otherwise force
  allow-list entries for code that cannot execute.
- **Stale entries are reported.** An allow-listed id that no longer matches any
  finding emits a warning, so the list cannot rot into a permanent blanket
  after the dependency is fixed or dropped.

### Duplicate runs on push + pull_request

The test workflows trigger on both events, so pushing to a branch that already
has an open PR fires twice — most visibly for a `develop` -> `main` PR, where
`develop` is in both trigger lists.

`push_branches` is the real fix: set it to just the default branch so a PR head
branch never fires `push` at all.

```yaml
ci:
  test_branches: [main, develop]   # PRs targeting these run checks
  push_branches: [main]            # only pushes to main run checks
```

Post-merge validation on the default branch is preserved and pre-merge
validation comes from the PR event, so nothing is unchecked *while a PR is
open*. The trade-off is real though: a push to `develop` with no open PR then
runs nothing.

Cancelling is not an adequate substitute. A cancelled run reports as cancelled,
never as success — GitHub will say "N successful, M cancelled" rather than
all-green, and a cancelled *required* check can hold up a merge. The duplicate
has to not exist rather than be killed after it starts.

If you would rather keep the duplication than lose CI on non-default-branch
pushes, leave `push_branches` unset. Both runs then complete and **both report
success** — you pay for the redundant jobs but the PR is unambiguously green.
That is a reasonable trade; the thing to avoid is the middle ground where the
duplicate is cancelled instead.

Concurrency grouping is deliberately keyed on `github.ref`, not the branch name:

```yaml
concurrency:
  group: test-go-${{ github.ref }}
  cancel-in-progress: true
```

`github.ref` is stable across pushes to the same PR (`refs/pull/N/merge`), so
this still cancels a run that a newer push supersedes — the case where
cancelling is the right outcome. It intentionally does *not* collapse the
push/pull_request pair for a single commit, because that produces a cancelled
check rather than a passing one.

### Reusing test workflows

`test-python.yml`, `test-npm.yml` and `test-go.yml` are generated with a
`workflow_call:` trigger, and `publish-python`, `publish-npm` and `publish-go`
all gate on them with
`uses: ./.github/workflows/test-<lang>.yml` rather than restating the matrix.
Generating both sides is what makes this safe — the filename and job id are known
to match. When a test workflow is not managed for a repo (excluded by
`only_workflows` or `skip_workflows`), the caller falls back to inlining a copy,
since a `uses:` pointing at a file the generator does not produce would be a
dangling reference.

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

### Tailoring the generated test jobs

The defaults assume every package of a language installs and tests the same way.
Where that does not hold, `ci.python.projects` overrides `install` and
`test_command` per project; anything unset falls back to the language-level
value. A single global install line otherwise forces the union of every
package's extras onto all of them:

```yaml
ci:
  python:
    install: 'pip install -e ".[dev]"'
    test_command: 'pytest tests/ -x'
    projects:
      my-server:
        install: 'pip install -e ".[dev,context,observability]"'
        test_command: 'pytest tests/ -m "not slow and not integration" -x'
```

`setup_steps` (before lint/install) and `extra_steps` (after the tests) inject
repo-specific steps that no template can know about — freeing disk before a
heavy run, or a regression gate that is not a test. Both exist at the language
level and per project, and both default `working_directory` to the project's own
directory:

```yaml
ci:
  python:
    setup_steps:
      - name: Free disk space
        run: sudo rm -rf /usr/share/dotnet /opt/ghc
    projects:
      my-server:
        extra_steps:
          - name: Retrieval eval gate
            run: my-eval gate
```

This is an escape hatch, not a workflow authoring surface: a step is a name and
a shell command, optionally with `if` and `working_directory`.

### Python packages that depend on each other

By default a python test job installs its in-repo siblings the same way any
outside consumer would: from PyPI. That means the job validates the working
tree against the *published* copy of its own sibling, so a bad release — or one
that simply has not happened yet — fails a suite that has nothing wrong with
it, and genuine drift between two packages in the same commit goes unnoticed.

`ci.python.install_local_deps` installs them from the checkout first, in
topological order, before installing the project:

```yaml
ci:
  python:
    install_local_deps: true
```

```yaml
      - name: Install in-repo dependencies (my-client)
        run: |
          pip install -e my-client

      - name: Install
        run: pip install -e ".[dev]"
        working-directory: my-langchain
```

Edges come from `dependency_mappings.python.dependencies`, the same graph that
orders the publish jobs. Unlike the npm chain this needs no job ordering and no
artifacts — a python package installs directly from source, so only the install
order matters — and the editable install satisfies the exact `==` pin that
`sync-versions` keeps in the manifest.

### TypeScript packages that depend on each other

`npm ci` does not build a `file:` dependency — npm runs `prepare` for those, not
`prepublishOnly` — so a package that type-checks against a sibling's `dist/`
fails in a test job that builds nothing. Setting `ci.npm.build: true` turns on
`npm run build` and, when `dependency_mappings.typescript.dependencies` declares
edges, chains the test jobs along them: each job waits on its transitive
dependencies, downloads their build output, and uploads its own if anything
depends on it.

```yaml
ci:
  npm:
    build: true
```

With `build` off the jobs stay independent and the output is unchanged, so this
costs nothing for repos whose packages do not reference each other.

### Independently-versioned packages

The publish workflows assume one `v*.*.*` tag drives every artifact. That holds
when a repo versions its packages in lockstep, and breaks in two ways when it
does not.

`test_projects` and `publish_projects` are independent allowlists. A package
can be worth publishing without being testable in CI yet — a suite blocked on
credentials, or on a broken published dependency — and shipping a job that is
known to be red trains people to ignore a red build. On the npm side a project
the allowlist omits is pulled back in when something kept depends on it, since
its build output is what makes the dependent testable at all.

**Committed build output.** `ci.npm.extra_steps` runs after the test step, which
is where a check on generated assets belongs — `build` has already regenerated
them by then. A repo that commits build output because something else consumes
it at compile time (a Go binary embedding an admin UI via `//go:embed`, say)
can fail the job when the committed copy no longer matches its source:

```yaml
ci:
  npm:
    build: true
    extra_steps:
      - name: Verify the embedded admin UI matches web/src
        working_directory: '.'          # the asset lives outside the npm package
        run: |
          if ! git diff --exit-code -- pkg/admin/ui; then
            echo "::error::pkg/admin/ui is stale; rebuild and commit it."
            exit 1
          fi
```

Committing build output is what lets `go build` and a cross-compile matrix run
without a Node toolchain; the cost is that it can fall behind silently, and this
turns that into a failed PR rather than a stale UI in a released binary.

On the npm side, a package whose `package.json` sets `"private": true` never
gets a publish job — no allow-list entry required. npm refuses to publish a
private package, so generating one could only ever produce a failing release,
and the flag is a better declaration of intent than a versions.yaml list: it
sits next to the package and it is what npm itself reads. Such packages are
still *tested*; private means "not for the registry", not "not built". Naming
one in `publish_projects` is a contradiction rather than an override, so it is
rejected with a message identifying both halves.

`publish_projects` is an allowlist of projects to generate publish jobs for.
A manifest is not a declaration of intent to publish — a repo can hold a package
that ships only as a container image, or a UI that never goes to npm — and the
default of "publish everything with a manifest" would make a public release of
it. Excluding a project also removes it from its dependents' `needs`, since an
unpublished project imposes no ordering constraint:

```yaml
ci:
  python:
    publish_projects: [ my-sdk, my-server ]   # my-embed-server ships as an image only
  npm:
    publish_projects: [ my-sdk-ts, my-mcp ]   # my-explorer is not an npm package
```

`skip_if_published` handles the other case: a package whose version did not
move since the last tag. PyPI and npm both reject re-uploading an existing
version, so without this the whole release job fails. The guard queries the
registry and skips only the upload — the build and any artifact upload still
run, so a skipped package still contributes to the GitHub release.

```yaml
ci:
  npm:
    skip_if_published: true
```

`skip_if_published` on the python side needs a static `version` in
`pyproject.toml`; a dynamic version fails the job with an explicit message
rather than guessing.

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
  test_branches: [main, develop]              # PR target branches; default: [main, develop]
  push_branches: [main]                       # branches whose pushes trigger CI; default: test_branches
  skip_workflows: []                          # workflow basenames (no .yml) to leave unmanaged
  only_workflows: []                          # allowlist; empty = manage everything that renders
  github_release: false                       # attach built dists to a GitHub release for the tag
  bootstrap_method: uvx                       # uvx | pip; default: uvx
  repo_tools_source: scitrera-repo-tools      # any uv/pip source spec; default: PyPI name
  python:
    test_versions: ["3.11", "3.12", "3.13"]   # default
    lint: ruff                                  # ruff | none; default: ruff
    format_check: false                         # also run `ruff format --check`
    install: 'pip install -e ".[test]"'         # default
    install_local_deps: false                   # install in-repo siblings from the checkout
    test_command: 'python -m pytest -v'         # default
    setup_steps: []                             # injected before lint/install
    extra_steps: []                             # injected after the test step
    projects: {}                                # per-project overrides, keyed by project name
    test_projects: []                           # projects to test; default [] = every python project
    pypi_environment: pypi                      # GitHub environment, default: pypi
    publish_requires_tests: true                # gate PyPI upload on the test matrix; default: true
    verify_tag_version: null                    # project name; fail if tag != its versions.yaml version
    publish_projects: []                        # projects to publish; default [] = every python project
    skip_if_published: false                    # skip upload when PyPI already serves this version
  npm:
    node_version: "24"                          # default: "24"
    lint: tsc-noemit                            # tsc-noemit | eslint | none
    build: false                                # run `npm run build` in test jobs
    cache: false                                # setup-node npm caching (needs a lockfile)
    test_projects: []                           # projects to test; deps of kept projects are pulled back in
    npm_environment: npm                        # default: npm
    use_provenance: false                       # add --provenance to npm publish
    use_oidc: false                             # skip NPM_TOKEN (trusted publisher)
    publish_requires_tests: true                # gate npm publish on test-npm.yml
    publish_projects: []                        # projects to publish; default [] = every TS project
    skip_if_published: false                    # skip publish when npm already serves this version
    setup_steps: []                             # injected before install
    extra_steps: []                             # injected after the test step
  go:
    go_version: "1.25.10"                       # default: from go_toolchain.go, else "1.25"
    lint: golangci-lint                          # golangci-lint | none; default: golangci-lint
    golangci_version: "v2.11.4"
    enable_govulncheck: true                    # default: true
    test_args: "-race -count=1"
    coverage: false                             # add -coverprofile/-covermode + upload artifact
    module_tags: none                           # none | verify | push (see publish-go below)
    verify_tag_version: null                    # project name; fail the release if tag != its versions.yaml version
    govulncheck_version: "v1.1.4"               # pinned; an unpinned scanner reddens unrelated PRs
    govulncheck_ignore: []                      # accepted-risk advisories; see below
    binaries: []                                # commands to cross-compile for the release; see above
    binary_platforms:                           # default matrix for entries declaring none
      [ linux/amd64, linux/arm64, darwin/amd64, darwin/arm64, windows/amd64, windows/arm64 ]
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
`type: package` / `type: gomod` / `type: gomod_require` rules), its workflows
are simply not generated.

**Declaring a Go module (`type: gomod`).** Python and TypeScript answer "which
directory is this project?" for free — `pyproject.toml` and `package.json` are
both the file a version is written into and the root of the thing CI builds. Go
has no version manifest at all (a module's version is a git tag), so discovery
historically fell back to the project's first `gomod_require` rule. That rule
exists to pin *other* modules' require lines, and the two come apart badly:

- a module with no in-repo requires has no `gomod_require` rule, so nothing
  identifies it and CI never sees it;
- a project whose only `gomod_require` targets a **nested** module points its
  entire Go lane at the wrong directory — `go test` runs against the wrong
  module, and `publish-go` reconciles a tag nobody resolves against.

`type: gomod` declares the module outright and rewrites nothing. It takes
precedence over `gomod_require` regardless of declaration order:

```yaml
project_rules:
  my-sdk-go:
    - { type: gomod,         path: sdk-go/go.mod }      # what CI operates on
    - { type: go_version,    path: sdk-go/doc.go }
    # pins the parent's version inside the nested module's require line
    - { type: gomod_require, path: sdk-go/aether/go.mod, args: [ example.com/repo/sdk-go ] }

  # A second module in the same tree gets its own entry. No version key: it is a
  # declaration for CI, so `sync-versions` skips it while `test-go`/`publish-go`
  # still cover it.
  my-sdk-go-aether:
    - { type: gomod, path: sdk-go/aether/go.mod }
```

Existing repos need no change — with no `gomod` rule the old `gomod_require`
fallback still applies.

**Go module caching and `go.sum`.** Every generated Go job keys the `setup-go`
cache on the module's `go.sum`. Pointing `cache-dependency-path` at a file that
does not exist is not a cache miss — the action fails the step with "Some
specified paths were not resolved, unable to cache dependencies", so the whole
Go lane goes red before compiling anything.

A module can legitimately have no `go.sum`: Go records checksums only for what
it downloads, so a module requiring nothing external — or whose every
requirement is redirected to a local directory by a `replace` — never gets the
file. Those modules render `cache: false` instead, since there is nothing to
cache either.

The other reason `go.sum` goes missing is that nobody committed it, and that
module cannot build from a clean checkout at all. Emitting `cache: false` for
it would swap a clear failure at generation time for a baffling one during
`go build`, so a `go.mod` with unreplaced requirements and no `go.sum` is a
**generation error** naming the directory to run `go mod tidy` in. Indirect
requirements count: they are downloaded and verified like any other.

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
      build_strategy: auto                     # auto | qemu | native | cross; default: auto
    aetherlite:
      context: server
      dockerfile: server/Dockerfile.aetherlite-dev
      needs: aether                            # cascade: child gets BASE_IMAGE=<reg>/aether:<base-tag>
      version_from: aether-gateway
    aetherlite-dev:
      context: server
      dockerfile: server/Dockerfile.aetherlite-dev
      needs: aetherlite
      image_name: aetherlite                   # push to `aetherlite`, not `aetherlite-dev`
      tag_style: dev                           # dev- prefixed tags; suppresses :latest
      version_from: aether-gateway
      # base_image_arg: BASE_IMAGE             # override the build-arg name (default: BASE_IMAGE)
    embed-server:
      context: .
      dockerfile: embed-server/Dockerfile
      build_args:                              # extra --build-arg values
        AETHER_VERSION: "${preferred_versions:container:ghcr.io/scitrera/aether}"
        AETHER_CLIENT_VERSION: "${preferred_versions:python:scitrera-aether-client}"
        FEATURE_FLAG: "1"                      # plain literals work too
        OPTIONAL_PIN: ""                       # explicitly empty is passed through
```

**Tag variants.** `tag_suffix` appends to every generated tag, `latest` included, so
two descriptors can publish build variants of one image into one repository —
a CPU build at `img:1.2.3` beside a CUDA one at `img:1.2.3-cuda13`, sharing
`image_name` and differing only by tag:

```yaml
    embed-server:
      context: .
      dockerfile: Dockerfile.cpu
    embed-server-cuda13:
      context: .
      dockerfile: Dockerfile
      image_name: embed-server                 # same repository
      tag_suffix: -cuda13                      # 1.2.3-cuda13, latest-cuda13
```

The suffix must start with `-`, `.` or `_`, otherwise it welds onto the version
(`1.2.3cuda13`) and reads as a different version rather than a variant. `latest` is
suffixed too (`onlatest=true`): without that the variant would claim the bare
`latest` tag and the two variants would silently overwrite whichever published last.
This differs from `tag_style: dev`, which *prefixes* and suppresses `latest`; the two
compose if a variant needs both.

**`${image_version}`** resolves, inside a `build_args` value, to the same version
the image is tagged with. A Dockerfile that stamps its artifact — `ARG VERSION`
feeding an ldflags `-X main.version=` or an OCI `image.version` label — needs
that number too, and hardcoding a second copy is a version that drifts silently
from the tag. Requires `version_from` on the descriptor: without it there is no
version to read, and an image that builds green while reporting a blank version
is worse than one that refuses to generate.

```yaml
    gateway:
      context: .
      dockerfile: Dockerfile
      version_from: llm-gateway
      build_args:
        VERSION: "${image_version}"        # also embeddable: "v${image_version}-oss"
```

**Build args.** `build_args` are **merged with** the `BASE_IMAGE` cascade, not an
alternative to it — an image can inherit from a parent *and* pin its own
arguments. Emission is sorted, so reordering the config does not surface as CI
drift. An explicit `""` is passed through (Dockerfiles commonly use an empty arg
to mean "no pin"); a `null` value is rejected, since that is almost always a YAML
accident rather than an intent.

**`${preferred_versions:<language>:<package>}`** substitutes a value declared in
the `preferred_versions:` block, so a version bundled into an image is pinned from
the same place every other dependency is pinned — the same reasoning that pins
`ruff` for the lint step and `protoc-gen-go` for the proto lane. The language
bucket is free-form (`container:` for image tags is as valid as `python:`), and
the package half may contain dots, slashes and `@`
(`google.golang.org/protobuf`, `@modelcontextprotocol/sdk`).

Substitution is **verbatim** and may be embedded in a larger string
(`"v${...}-gpu"`). Preferred versions hold both bare pins (`0.0.69`) and specs
(`>=0.2.2`), and only the consuming Dockerfile knows which it needs — a
`pkg==${ARG}` line requires a bare pin — so no conversion between the two is
attempted. References resolve at **parse time**: an unknown language, an unknown
package, or a declared-but-empty value is a config error naming the file, rather
than an empty build-arg that builds green and ships a subtly wrong image.

Unknown keys in an image descriptor are rejected, so `buld_args:` fails loudly
instead of being silently ignored.

**Image naming.** By default the descriptor key *is* the pushed repository name.
`image_name` decouples them, which is required when two descriptors publish to
one repository distinguished only by tag — above, `aetherlite:*` and
`aetherlite:dev-*` are built by separate jobs from the same Dockerfile. Job ids
stay keyed on the descriptor (`build-aetherlite-dev`), so they never collide, and
a child's `BASE_IMAGE` follows the parent's overridden name.

**Cascade semantics.** When image B `needs: A`, B's build job depends on
A's build (or merge) job, and `BASE_IMAGE=<primary-registry>/A:<A's base-tag>`
is injected as a build-arg so B's Dockerfile picks up exactly the image A
just produced.

**Build strategy.** `auto` (the default) picks `native` when every platform
listed for the image has an entry in `ci.docker.platform_runners`; otherwise
it falls back to a single QEMU job. `qemu`, `native`, and `cross` force one
path explicitly. `cross` emits one multi-platform BuildKit job without QEMU;
it is intended for Dockerfiles that run build stages on `$BUILDPLATFORM` and
cross-compile artifacts for `$TARGETOS`/`$TARGETARCH` without executing target
binaries. In `native` mode, the generator emits one job per platform
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
