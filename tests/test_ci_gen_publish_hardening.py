"""Publish-side gates, bootstrap method, and the ruff pin.

These cover the guarantees that make a tag push safe: an upload cannot happen
before the test matrix and the tag/version check pass, and the tool that
rewrites version pins is resolved from a declared source.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import (
    build_publish_python,
    build_test_python,
    build_version_check,
)
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

BASE = (
    "py-a: 0.1.0\n"
    "project_rules:\n"
    "  py-a: [{ type: pyproject, path: py-a/pyproject.toml }]\n"
)


def _repo(tmp_path: Path, extra: str = "") -> Path:
    (tmp_path / "py-a").mkdir()
    (tmp_path / "py-a" / "pyproject.toml").write_text(
        "[project]\nname='py-a'\nversion='0.0.0'\n"
    )
    (tmp_path / "versions.yaml").write_text(BASE + extra, encoding="utf-8")
    return tmp_path


def _publish(tmp_path: Path, extra: str = "") -> dict:
    config = load_config(_repo(tmp_path, extra) / "versions.yaml")
    return yaml.safe_load(build_publish_python(config, config.ci))


# --- publish gates ---------------------------------------------------------


def test_publish_waits_on_test_matrix_by_default(tmp_path: Path) -> None:
    """Publishing must not be able to race the tests.

    The gate is now the generated test workflow rather than a copy of its
    matrix, so assert the call exists and that publish depends on it.
    """
    jobs = _publish(tmp_path)["jobs"]
    assert jobs["tests"]["uses"] == "./.github/workflows/test-python.yml"
    assert "tests" in jobs["publish-py-a"]["needs"]


def test_publish_requires_tests_can_be_disabled(tmp_path: Path) -> None:
    jobs = _publish(
        tmp_path, "ci:\n  python:\n    publish_requires_tests: false\n"
    )["jobs"]
    assert "test-py-a" not in jobs
    assert jobs["publish-py-a"].get("needs") in (None, [])


def test_verify_tag_job_absent_by_default(tmp_path: Path) -> None:
    """A single `v*.*.*` tag cannot identify a project, so this stays opt-in."""
    assert "verify-tag" not in _publish(tmp_path)["jobs"]


def test_verify_tag_job_gates_publish(tmp_path: Path) -> None:
    parsed = _publish(
        tmp_path, "ci:\n  python:\n    verify_tag_version: py-a\n"
    )
    jobs = parsed["jobs"]
    assert "verify-tag" in jobs
    assert "verify-tag" in jobs["publish-py-a"]["needs"]

    steps = jobs["verify-tag"]["steps"]
    compare = next(s for s in steps if s.get("name") == "Compare tag against versions.yaml")
    assert compare["if"] == "github.ref_type == 'tag'"
    assert "--print-version py-a" in compare["run"]
    # The drift check closes the hole left by version-check.yml running only on PRs.
    assert any("sync-versions --check" in str(s.get("run", "")) for s in steps)


def test_verify_tag_version_rejects_unknown_project(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a known project"):
        load_config(
            _repo(tmp_path, "ci:\n  python:\n    verify_tag_version: nope\n")
            / "versions.yaml"
        )


# --- github release --------------------------------------------------------


def test_github_release_absent_by_default(tmp_path: Path) -> None:
    parsed = _publish(tmp_path)
    assert "github-release" not in parsed["jobs"]
    assert "upload-artifact" not in yaml.dump(parsed)


def test_github_release_attaches_uploaded_dists(tmp_path: Path) -> None:
    jobs = _publish(tmp_path, "ci:\n  github_release: true\n")["jobs"]

    upload = next(
        s for s in jobs["publish-py-a"]["steps"] if s.get("name") == "Upload distributions"
    )
    assert upload["with"]["name"] == "dist-py-a"
    assert upload["with"]["if-no-files-found"] == "error"

    release = jobs["github-release"]
    assert release["needs"] == ["publish-py-a"]
    assert release["permissions"]["contents"] == "write"
    download = release["steps"][0]
    # The upload names and the download pattern have to agree or the release
    # is silently created with no files attached.
    assert download["with"]["pattern"] == "dist-*"


def test_publish_job_graph_is_closed(tmp_path: Path) -> None:
    """Every `needs` target must be a job defined in the same workflow."""
    jobs = _publish(
        tmp_path,
        "ci:\n  github_release: true\n  python:\n    verify_tag_version: py-a\n",
    )["jobs"]
    for name, job in jobs.items():
        for dep in job.get("needs", []):
            assert dep in jobs, f"job '{name}' needs undefined job '{dep}'"


# --- bootstrap -------------------------------------------------------------


def _version_check(tmp_path: Path, extra: str = "") -> str:
    config = load_config(_repo(tmp_path, extra) / "versions.yaml")
    return build_version_check(config, config.ci)


def test_bootstrap_defaults_to_uvx_from_pypi(tmp_path: Path) -> None:
    text = _version_check(tmp_path)
    assert "astral-sh/setup-uv@" in text
    assert "uvx --from 'scitrera-repo-tools' sync-versions --check" in text


def test_bootstrap_source_override(tmp_path: Path) -> None:
    text = _version_check(tmp_path, "ci:\n  repo_tools_source: '.'\n")
    assert "uvx --from '.' sync-versions --check" in text


def test_bootstrap_pip_method(tmp_path: Path) -> None:
    text = _version_check(
        tmp_path,
        "ci:\n  bootstrap_method: pip\n  repo_tools_source: 'scitrera-repo-tools==1.2.3'\n",
    )
    assert "setup-uv" not in text
    assert "pip install scitrera-repo-tools==1.2.3" in text
    # Under pip the console script is on PATH, so no uvx wrapper.
    assert "uvx" not in text
    assert "run: sync-versions --check --verbose" in text


def test_bootstrap_method_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="bootstrap_method"):
        load_config(
            _repo(tmp_path, "ci:\n  bootstrap_method: conda\n") / "versions.yaml"
        )


def test_repo_tools_source_rejects_quote_injection(tmp_path: Path) -> None:
    """The value lands inside a single-quoted shell argument."""
    with pytest.raises(ConfigError, match="single quotes"):
        load_config(
            _repo(tmp_path, "ci:\n  repo_tools_source: \"'; rm -rf /; '\"\n")
            / "versions.yaml"
        )


# --- ruff pin --------------------------------------------------------------


def test_ruff_unpinned_without_preferred_version(tmp_path: Path) -> None:
    config = load_config(_repo(tmp_path) / "versions.yaml")
    assert "pip install ruff\n" in build_test_python(config, config.ci)


def test_ruff_pinned_from_preferred_versions(tmp_path: Path) -> None:
    config = load_config(
        _repo(tmp_path, 'preferred_versions:\n  python:\n    "ruff": "0.16.0"\n')
        / "versions.yaml"
    )
    assert "pip install ruff==0.16.0" in build_test_python(config, config.ci)


def test_ruff_pin_preserves_operator_form(tmp_path: Path) -> None:
    config = load_config(
        _repo(tmp_path, 'preferred_versions:\n  python:\n    "ruff": ">=0.16"\n')
        / "versions.yaml"
    )
    assert "pip install ruff>=0.16" in build_test_python(config, config.ci)


def test_ruff_pin_reaches_publish_gate_tests(tmp_path: Path) -> None:
    """The pin must reach whichever test jobs gate the publish.

    When the test workflow is managed, publish calls it and the pin lives there.
    When it is not, publish inlines a copy and the pin has to follow it inline —
    an unpinned linter turning a release red is the failure being prevented, so
    both routes are checked.
    """
    pin = 'preferred_versions:\n  python:\n    "ruff": "0.16.0"\n'

    for sub in ("called", "inlined"):
        (tmp_path / sub).mkdir()

    called = _publish(tmp_path / "called", pin)
    assert called["jobs"]["tests"]["uses"] == "./.github/workflows/test-python.yml"

    inlined = _publish(
        tmp_path / "inlined", pin + "ci:\n  only_workflows: [publish-python]\n"
    )
    assert "tests" not in inlined["jobs"]
    assert "ruff==0.16.0" in yaml.dump(inlined)
