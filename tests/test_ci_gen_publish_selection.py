"""Publish allowlists (`publish_projects`) and the already-published guard.

Both exist for repos whose packages are versioned independently of the release
tag: not every manifest is meant for a public registry, and a package whose
version did not move must not be re-uploaded.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import (
    build_publish_npm,
    build_publish_python,
)
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

BODY = """\
py-lib: 0.1.0
py-app: 0.1.0
ts-lib: 0.1.0
ts-app: 0.1.0

project_rules:
  py-lib:
    - {{ type: pyproject, path: pylib/pyproject.toml }}
  py-app:
    - {{ type: pyproject, path: pyapp/pyproject.toml }}
  ts-lib:
    - {{ type: package, path: tslib/package.json }}
  ts-app:
    - {{ type: package, path: tsapp/package.json }}

dependency_mappings:
  python:
    packages:
      py-lib: pylib
    dependencies:
      py-app: [py-lib]
  typescript:
    packages:
      ts-lib: "@x/tslib"
    dependencies:
      ts-app: [ts-lib]

ci:
{ci_body}
"""


def _cfg(tmp_path: Path, write_file, write_json, ci_body: str):
    write_file(tmp_path / "pylib/pyproject.toml", '[project]\nname = "pylib"\nversion = "0.1.0"\n')
    write_file(tmp_path / "pyapp/pyproject.toml", '[project]\nname = "pyapp"\nversion = "0.1.0"\n')
    write_json(tmp_path / "tslib/package.json", {"name": "@x/tslib", "version": "0.1.0"})
    write_json(tmp_path / "tsapp/package.json", {"name": "@x/tsapp", "version": "0.1.0"})
    write_file(tmp_path / "versions.yaml", BODY.format(ci_body=ci_body))
    return load_config(tmp_path / "versions.yaml")


def _py_jobs(tmp_path, write_file, write_json, ci_body: str) -> dict:
    cfg = _cfg(tmp_path, write_file, write_json, ci_body)
    return yaml.safe_load(build_publish_python(cfg, cfg.ci))["jobs"]


def _npm_jobs(tmp_path, write_file, write_json, ci_body: str) -> dict:
    cfg = _cfg(tmp_path, write_file, write_json, ci_body)
    return yaml.safe_load(build_publish_npm(cfg, cfg.ci))["jobs"]


# --- publish_projects ------------------------------------------------------


def test_empty_allowlist_publishes_every_project(tmp_path, write_file, write_json):
    jobs = _py_jobs(tmp_path, write_file, write_json, "  test_branches: [main]\n")
    assert {"publish-py-lib", "publish-py-app"} <= set(jobs)


def test_allowlist_drops_excluded_python_project(tmp_path, write_file, write_json):
    jobs = _py_jobs(
        tmp_path, write_file, write_json,
        "  python:\n    publish_projects: [py-lib]\n",
    )
    assert "publish-py-lib" in jobs
    assert "publish-py-app" not in jobs


def test_excluded_dependency_is_dropped_from_dependent_needs(tmp_path, write_file, write_json):
    """A job that survives must not reference one that was filtered out."""
    jobs = _py_jobs(
        tmp_path, write_file, write_json,
        "  python:\n    publish_projects: [py-app]\n",
    )
    assert "publish-py-lib" not in jobs
    assert "publish-py-lib" not in jobs["publish-py-app"].get("needs", [])
    for name, job in jobs.items():
        for dep in job.get("needs", []):
            assert dep in jobs, f"job '{name}' needs undefined job '{dep}'"


def test_npm_allowlist_drops_excluded_project(tmp_path, write_file, write_json):
    jobs = _npm_jobs(
        tmp_path, write_file, write_json,
        "  npm:\n    publish_projects: [ts-lib]\n",
    )
    assert "publish-ts-lib" in jobs
    assert "publish-ts-app" not in jobs


def test_allowlist_rejects_unknown_project(tmp_path, write_file, write_json):
    with pytest.raises(ConfigError, match="unknown project"):
        _cfg(tmp_path, write_file, write_json,
             "  python:\n    publish_projects: [nope]\n")


def test_allowlist_rejects_wrong_language_project(tmp_path, write_file, write_json):
    """`ts-lib` is a real project, just not a python one."""
    cfg = _cfg(tmp_path, write_file, write_json,
               "  python:\n    publish_projects: [ts-lib]\n")
    with pytest.raises(ValueError, match="not python project"):
        build_publish_python(cfg, cfg.ci)


# --- skip_if_published -----------------------------------------------------


def test_no_guard_by_default(tmp_path, write_file, write_json):
    jobs = _py_jobs(tmp_path, write_file, write_json, "  test_branches: [main]\n")
    steps = jobs["publish-py-lib"]["steps"]
    assert not any(s.get("id") == "published" for s in steps)
    assert all("if" not in s for s in steps)


def test_pypi_guard_gates_only_the_upload(tmp_path, write_file, write_json):
    jobs = _py_jobs(
        tmp_path, write_file, write_json,
        "  python:\n    skip_if_published: true\n",
    )
    steps = jobs["publish-py-lib"]["steps"]
    guard = next(s for s in steps if s.get("id") == "published")
    assert "pypi.org/pypi/$name/$version/json" in guard["run"]

    publish = next(s for s in steps if "gh-action-pypi-publish" in str(s.get("uses", "")))
    assert publish["if"] == "steps.published.outputs.skip != 'true'"

    # The build must stay unconditional, or a skipped publish would also drop
    # the artifact the GitHub release collects.
    build = next(s for s in steps if s.get("name") == "Build sdist + wheel")
    assert "if" not in build


def test_npm_guard_gates_only_the_publish(tmp_path, write_file, write_json):
    jobs = _npm_jobs(
        tmp_path, write_file, write_json,
        "  npm:\n    skip_if_published: true\n",
    )
    steps = jobs["publish-ts-lib"]["steps"]
    guard = next(s for s in steps if s.get("id") == "published")
    assert "npm view" in guard["run"]

    publish = next(s for s in steps if s.get("name") == "Publish to npm")
    assert publish["if"] == "steps.published.outputs.skip != 'true'"
    build = next(s for s in steps if s.get("name") == "Build")
    assert "if" not in build


def test_guard_reads_version_after_build(tmp_path, write_file, write_json):
    """The guard must see the version that is about to ship, not an earlier one."""
    jobs = _npm_jobs(
        tmp_path, write_file, write_json,
        "  npm:\n    skip_if_published: true\n",
    )
    names = [s.get("name") for s in jobs["publish-ts-lib"]["steps"]]
    assert names.index("Build") < names.index(
        "Check whether this version is already published"
    )


def test_skip_if_published_rejects_non_bool(tmp_path, write_file, write_json):
    with pytest.raises(ConfigError):
        _cfg(tmp_path, write_file, write_json,
             "  npm:\n    skip_if_published: yes-please\n")


# --- test_projects ---------------------------------------------------------


def test_test_projects_scopes_the_test_workflow(tmp_path, write_file, write_json):
    from scitrera_repo_tools.ci_gen_gha.templates import build_test_python

    cfg = _cfg(tmp_path, write_file, write_json,
               "  python:\n    test_projects: [py-lib]\n")
    jobs = yaml.safe_load(build_test_python(cfg, cfg.ci))["jobs"]
    assert set(jobs) == {"test-py-lib"}


def test_test_projects_is_independent_of_publish_projects(tmp_path, write_file, write_json):
    """A package can be publishable without being testable in CI yet."""
    from scitrera_repo_tools.ci_gen_gha.templates import build_test_python

    cfg = _cfg(tmp_path, write_file, write_json,
               "  python:\n    test_projects: [py-lib]\n    publish_projects: [py-lib, py-app]\n")
    tested = set(yaml.safe_load(build_test_python(cfg, cfg.ci))["jobs"])
    published = {
        j for j in yaml.safe_load(build_publish_python(cfg, cfg.ci))["jobs"]
        if j.startswith("publish-")
    }
    assert tested == {"test-py-lib"}
    assert published == {"publish-py-lib", "publish-py-app"}


def test_test_projects_rejects_wrong_language(tmp_path, write_file, write_json):
    from scitrera_repo_tools.ci_gen_gha.templates import build_test_python

    cfg = _cfg(tmp_path, write_file, write_json,
               "  python:\n    test_projects: [ts-lib]\n")
    with pytest.raises(ValueError, match="not python project"):
        build_test_python(cfg, cfg.ci)
