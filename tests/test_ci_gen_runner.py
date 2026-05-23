"""Runner: write/check/diff semantics for generate-ci-gha."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.ci_gen_gha.runner import run
from scitrera_repo_tools.version_sync.config import load_config


@pytest.fixture
def py_repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "pyproject.toml").write_text("[project]\nversion='0.0.0'\n")
    (tmp_path / "versions.yaml").write_text(
        "pkg: 0.1.0\n"
        "project_rules:\n"
        "  pkg: [{ type: pyproject, path: pkg/pyproject.toml }]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_first_run_creates_missing_files(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"

    rc = run(config, workflows_dir=workflows, force=False, check_only=False)
    assert rc == 0

    assert (workflows / "version-check.yml").is_file()
    assert (workflows / "test-python.yml").is_file()
    assert (workflows / "publish-python.yml").is_file()
    # No npm projects → these stay absent.
    assert not (workflows / "test-npm.yml").exists()
    assert not (workflows / "publish-npm.yml").exists()


def test_second_run_is_noop_when_in_sync(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"

    run(config, workflows_dir=workflows, force=False, check_only=False)
    before = (workflows / "test-python.yml").read_text()
    rc = run(config, workflows_dir=workflows, force=False, check_only=False)
    after = (workflows / "test-python.yml").read_text()
    assert rc == 0
    assert before == after


def test_drift_without_force_exits_one_and_does_not_overwrite(
    py_repo: Path,
) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"

    run(config, workflows_dir=workflows, force=False, check_only=False)
    drifted = workflows / "test-python.yml"
    drifted.write_text("# hand-edited do not touch\n")

    rc = run(config, workflows_dir=workflows, force=False, check_only=False)
    assert rc == 1
    assert drifted.read_text() == "# hand-edited do not touch\n"


def test_drift_with_force_overwrites(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"

    run(config, workflows_dir=workflows, force=False, check_only=False)
    drifted = workflows / "test-python.yml"
    drifted.write_text("# stale\n")

    rc = run(config, workflows_dir=workflows, force=True, check_only=False)
    assert rc == 0
    assert "test-pkg" in drifted.read_text()


def test_check_only_never_writes(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"

    rc = run(config, workflows_dir=workflows, force=False, check_only=True)
    assert rc == 1  # would-be-created counts as failure under --check
    assert not (workflows / "test-python.yml").exists()


def test_check_only_passes_when_in_sync(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"
    run(config, workflows_dir=workflows, force=False, check_only=False)

    rc = run(config, workflows_dir=workflows, force=False, check_only=True)
    assert rc == 0


def test_check_only_reports_drift_without_writing(py_repo: Path) -> None:
    config = load_config(py_repo / "versions.yaml")
    workflows = py_repo / ".github" / "workflows"
    run(config, workflows_dir=workflows, force=False, check_only=False)

    drifted = workflows / "test-python.yml"
    drifted.write_text("# manual\n")

    rc = run(config, workflows_dir=workflows, force=False, check_only=True)
    assert rc == 1
    assert drifted.read_text() == "# manual\n"
