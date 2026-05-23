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

## `generate-ci`

Generates GitHub Actions workflows from `versions.yaml`. Produces up to five
files in `.github/workflows/`:

| File | Trigger | Purpose |
|---|---|---|
| `version-check.yml` | PR (paths-filtered) | Fail PRs that drift from `versions.yaml` |
| `test-python.yml` | push/PR to `test_branches` | Matrix test across Python versions, per project |
| `test-npm.yml` | push/PR to `test_branches` | Per-TS-project install + type-check + `npm test` |
| `publish-python.yml` | tag `v*.*.*` push | Per-project PyPI publish in dependency order |
| `publish-npm.yml` | tag `v*.*.*` push | Per-project npm publish in dependency order |

The publish workflows respect the DAG defined by
`dependency_mappings.<lang>.dependencies` — every consumer's job declares
`needs: [publish-<dep>, ...]` so internal deps publish first. Both publish
workflows run `sync-versions --release` inline to rewrite local refs
(`workspace:`, `file:`, `git+...`, PEP 508 direct refs) into version pins
before building, so published artifacts are installable from PyPI/npm
without the original repo checkout.

### Behavior

```bash
generate-ci             # write missing files; show unified diff for drift; exit 1 on drift
generate-ci --force     # overwrite drift
generate-ci --check     # never write; CI-friendly drift detector
```

Default (no flags) creates files on first run in a fresh repo, and acts as
a drift check on subsequent runs — safe to wire into CI.

### `ci:` block in `versions.yaml`

All keys optional; sensible defaults applied for anything you omit.

```yaml
ci:
  test_branches: [main, develop]              # default: [main, develop]
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
```

If a language has no `project_rules` entries (no `type: pyproject` /
`type: package` rules), its workflows are simply not generated.

## License

BSD 3-Clause.
