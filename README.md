# scitrera-repo-tools

Centralized monorepo version-sync tool driven by `versions.yaml`.

## Install

```bash
pip install scitrera-repo-tools
# or, from source:
pip install -e .
```

## Usage

From any directory inside a monorepo containing a `versions.yaml`:

```bash
sync-versions            # apply updates
sync-versions --check    # dry-run, exit 1 on drift
sync-versions --verbose  # show every file inspected
sync-versions --config path/to/versions.yaml
```

## `versions.yaml` schema

```yaml
# Top-level project versions
my-python-pkg: 0.1.22
my-ts-pkg: 0.1.22

# External dep pins per language (optional)
preferred_versions:
  python:
    "pydantic": "2.13.4"
  typescript:
    "@modelcontextprotocol/sdk": "^1.26.0"

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
```

## Releases

Releases are automated via GitHub Actions on tag push (`v*.*.*`):

1. CI runs the test suite on Python 3.11/3.12/3.13.
2. A guard step asserts the tag matches `pyproject.toml`'s `[project].version`.
3. `python -m build` produces an sdist + wheel.
4. The artifacts are published to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/) (OIDC; no API token).
5. A GitHub Release is created with the artifacts attached.

## License

BSD 3-Clause.
