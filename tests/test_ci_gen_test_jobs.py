"""Test-job customization: per-project overrides, injected steps, npm chaining.

These cover the ways a real monorepo's test jobs differ from the generator's
one-size default — different extras per package, a regression gate that is not a
test, and TypeScript packages that must build in dependency order.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_test_npm, build_test_python
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

PY_BODY = """\
py-server: 0.1.0
py-sdk: 0.1.0

project_rules:
  py-server:
    - {{ type: pyproject, path: server/pyproject.toml }}
  py-sdk:
    - {{ type: pyproject, path: sdk/pyproject.toml }}

ci:
{ci_body}
"""

TS_BODY = """\
ts-sdk: 0.1.0
ts-mcp: 0.1.0
ts-plugin: 0.1.0
ts-ui: 0.1.0

project_rules:
  ts-sdk:
    - {{ type: package, path: sdk/package.json }}
  ts-mcp:
    - {{ type: package, path: mcp/package.json }}
  ts-plugin:
    - {{ type: package, path: plugin/package.json }}
  ts-ui:
    - {{ type: package, path: ui/package.json }}

dependency_mappings:
  typescript:
    packages:
      ts-sdk: "@x/sdk"
      ts-mcp: "@x/mcp"
    dependencies:
      ts-mcp: [ts-sdk]
      ts-plugin: [ts-mcp]

ci:
{ci_body}
"""


def _py(tmp_path: Path, write_file, ci_body: str) -> dict:
    write_file(tmp_path / "server/pyproject.toml", '[project]\nname = "s"\nversion = "0.1.0"\n')
    write_file(tmp_path / "sdk/pyproject.toml", '[project]\nname = "k"\nversion = "0.1.0"\n')
    write_file(tmp_path / "versions.yaml", PY_BODY.format(ci_body=ci_body))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_python(cfg, cfg.ci))["jobs"]


def _ts(tmp_path: Path, write_file, write_json, ci_body: str) -> dict:
    for d, n in (("sdk", "@x/sdk"), ("mcp", "@x/mcp"), ("plugin", "@x/plugin"), ("ui", "@x/ui")):
        write_json(tmp_path / d / "package.json", {"name": n, "version": "0.1.0"})
    write_file(tmp_path / "versions.yaml", TS_BODY.format(ci_body=ci_body))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_npm(cfg, cfg.ci))["jobs"]


def _step(job: dict, name: str) -> dict:
    return next(s for s in job["steps"] if s.get("name") == name)


# --- per-project install / test command ------------------------------------


def test_global_install_and_test_command_apply_to_all(tmp_path, write_file):
    jobs = _py(tmp_path, write_file,
               "  python:\n    install: 'pip install -e \".[dev]\"'\n    test_command: 'pytest -x'\n")
    for job in jobs.values():
        assert _step(job, "Install")["run"] == 'pip install -e ".[dev]"'
        assert _step(job, "Run tests")["run"] == "pytest -x"


def test_per_project_override_wins(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, """\
  python:
    install: 'pip install -e ".[dev]"'
    test_command: 'pytest -x'
    projects:
      py-server:
        install: 'pip install -e ".[dev,observability]"'
        test_command: 'pytest -m "not slow" -x'
""")
    assert _step(jobs["test-py-server"], "Install")["run"] == 'pip install -e ".[dev,observability]"'
    assert _step(jobs["test-py-server"], "Run tests")["run"] == 'pytest -m "not slow" -x'
    # The project without an entry keeps the language-level values.
    assert _step(jobs["test-py-sdk"], "Install")["run"] == 'pip install -e ".[dev]"'
    assert _step(jobs["test-py-sdk"], "Run tests")["run"] == "pytest -x"


def test_projects_rejects_unknown_project(tmp_path, write_file):
    with pytest.raises(ConfigError, match="unknown project"):
        _py(tmp_path, write_file, "  python:\n    projects:\n      nope:\n        install: x\n")


def test_projects_rejects_unknown_key(tmp_path, write_file):
    with pytest.raises(ConfigError, match="unknown key"):
        _py(tmp_path, write_file,
            "  python:\n    projects:\n      py-sdk:\n        instal: typo\n")


# --- injected steps --------------------------------------------------------


def test_setup_steps_run_before_install(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, """\
  python:
    setup_steps:
      - name: Free disk space
        run: sudo rm -rf /opt/ghc
""")
    names = [s.get("name") for s in jobs["test-py-sdk"]["steps"]]
    assert names.index("Free disk space") < names.index("Install")


def test_extra_steps_run_after_tests(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, """\
  python:
    projects:
      py-server:
        extra_steps:
          - name: Retrieval eval gate
            run: my-eval gate
""")
    names = [s.get("name") for s in jobs["test-py-server"]["steps"]]
    assert names.index("Retrieval eval gate") > names.index("Run tests")
    # Scoped to the project that declared it.
    assert "Retrieval eval gate" not in [s.get("name") for s in jobs["test-py-sdk"]["steps"]]


def test_injected_step_defaults_to_project_directory(tmp_path, write_file):
    jobs = _py(tmp_path, write_file,
               "  python:\n    extra_steps:\n      - name: Ping\n        run: echo hi\n")
    assert _step(jobs["test-py-server"], "Ping")["working-directory"] == "server"


def test_injected_step_honors_explicit_directory_and_if(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, """\
  python:
    extra_steps:
      - name: Ping
        run: echo hi
        working_directory: .
        if: github.event_name == 'push'
""")
    step = _step(jobs["test-py-sdk"], "Ping")
    assert step["working-directory"] == "."
    assert step["if"] == "github.event_name == 'push'"


def test_multiline_injected_step_survives_yaml_round_trip(tmp_path, write_file):
    """A run body that dedents out of the block scalar corrupts the file."""
    jobs = _py(tmp_path, write_file, """\
  python:
    extra_steps:
      - name: Multi
        run: |
          set -euo pipefail
          if [ -f x ]; then
            echo "nested"
          fi
""")
    run = _step(jobs["test-py-sdk"], "Multi")["run"]
    assert "set -euo pipefail" in run
    assert '  echo "nested"' in run


def test_step_requires_name_and_run(tmp_path, write_file):
    with pytest.raises(ConfigError, match="run"):
        _py(tmp_path, write_file,
            "  python:\n    extra_steps:\n      - name: Ping\n")


# --- ruff format check -----------------------------------------------------


def test_format_check_off_by_default(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, "  test_branches: [main]\n")
    assert "ruff format" not in _step(jobs["test-py-sdk"], "Lint with ruff")["run"]


def test_format_check_adds_format_step(tmp_path, write_file):
    jobs = _py(tmp_path, write_file, "  python:\n    format_check: true\n")
    run = _step(jobs["test-py-sdk"], "Lint with ruff")["run"]
    assert "ruff check ." in run
    assert "ruff format --check ." in run


# --- npm build / cache / chaining ------------------------------------------


def test_npm_jobs_independent_without_build(tmp_path, write_file, write_json):
    """Default output is unchanged: no ordering, no artifacts, no build."""
    jobs = _ts(tmp_path, write_file, write_json, "  test_branches: [main]\n")
    for job in jobs.values():
        assert job.get("needs") is None
        assert not any("artifact" in str(s.get("uses", "")) for s in job["steps"])
        assert not any(s.get("name") == "Build" for s in job["steps"])


def test_npm_build_and_cache(tmp_path, write_file, write_json):
    jobs = _ts(tmp_path, write_file, write_json, "  npm:\n    build: true\n    cache: true\n")
    setup = next(s for s in jobs["test-ts-sdk"]["steps"] if "setup-node" in str(s.get("uses", "")))
    assert setup["with"]["cache"] == "npm"
    assert setup["with"]["cache-dependency-path"] == "sdk/package-lock.json"
    assert _step(jobs["test-ts-sdk"], "Build")["run"] == "npm run build --if-present"


def test_npm_chain_orders_jobs_and_threads_dist(tmp_path, write_file, write_json):
    jobs = _ts(tmp_path, write_file, write_json, "  npm:\n    build: true\n")

    assert jobs["test-ts-sdk"].get("needs") is None
    assert jobs["test-ts-mcp"]["needs"] == ["test-ts-sdk"]
    # Two hops down, the transitive dependency must still be present: the
    # artifact is only downloadable once the job that uploads it has run.
    assert jobs["test-ts-plugin"]["needs"] == ["test-ts-mcp", "test-ts-sdk"]

    downloads = [
        s["with"]["name"] for s in jobs["test-ts-plugin"]["steps"]
        if "download-artifact" in str(s.get("uses", ""))
    ]
    assert set(downloads) == {"ts-dist-ts-mcp", "ts-dist-ts-sdk"}


def test_npm_uploads_only_what_something_depends_on(tmp_path, write_file, write_json):
    jobs = _ts(tmp_path, write_file, write_json, "  npm:\n    build: true\n")

    def uploads(job):
        return [s for s in jobs[job]["steps"] if "upload-artifact" in str(s.get("uses", ""))]

    assert uploads("test-ts-sdk")          # depended on by ts-mcp
    assert uploads("test-ts-mcp")          # depended on by ts-plugin
    assert not uploads("test-ts-plugin")   # leaf
    assert not uploads("test-ts-ui")       # no edges at all


def test_npm_chain_downloads_before_install(tmp_path, write_file, write_json):
    """npm may copy a file: dependency, so its output must already be on disk."""
    jobs = _ts(tmp_path, write_file, write_json, "  npm:\n    build: true\n")
    steps = jobs["test-ts-mcp"]["steps"]
    dl = next(i for i, s in enumerate(steps) if "download-artifact" in str(s.get("uses", "")))
    install = next(i for i, s in enumerate(steps) if s.get("name") == "Install")
    assert dl < install


def test_npm_chain_job_graph_is_closed(tmp_path, write_file, write_json):
    jobs = _ts(tmp_path, write_file, write_json, "  npm:\n    build: true\n")
    for name, job in jobs.items():
        for dep in job.get("needs", []):
            assert dep in jobs, f"job '{name}' needs undefined job '{dep}'"
