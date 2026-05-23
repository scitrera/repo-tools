"""ci.skip_workflows: drop a workflow from generator management entirely."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

from scitrera_repo_tools.ci_gen_gha.runner import run
from scitrera_repo_tools.version_sync.config import load_config


def _py_repo(tmp_path: Path, *, skip: list = None) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "pyproject.toml").write_text("[project]\nversion='0.0.0'\n")
    skip_block = ""
    if skip:
        skip_block = "ci:\n  skip_workflows: [" + ", ".join(skip) + "]\n"
    (tmp_path / "versions.yaml").write_text(
        "pkg: 0.1.0\n"
        "project_rules:\n"
        "  pkg: [{ type: pyproject, path: pkg/pyproject.toml }]\n"
        + skip_block,
        encoding="utf-8",
    )
    return tmp_path


def test_skip_workflow_not_generated(tmp_path: Path) -> None:
    repo = _py_repo(tmp_path, skip=["test-python"])
    config = load_config(repo / "versions.yaml")
    workflows = repo / ".github" / "workflows"
    rc = run(config, workflows_dir=workflows, force=False, check_only=False)
    assert rc == 0
    assert (workflows / "version-check.yml").is_file()
    assert (workflows / "publish-python.yml").is_file()
    assert not (workflows / "test-python.yml").exists()


def test_skip_preserves_hand_edited_file(tmp_path: Path) -> None:
    """A skipped workflow's on-disk content is never overwritten or reported as drift."""
    repo = _py_repo(tmp_path, skip=["test-python"])
    config = load_config(repo / "versions.yaml")
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "test-python.yml").write_text("# hand-maintained\n")

    rc = run(config, workflows_dir=workflows, force=False, check_only=False)
    assert rc == 0
    assert (workflows / "test-python.yml").read_text() == "# hand-maintained\n"


def test_skip_check_mode_does_not_report_drift(tmp_path: Path) -> None:
    repo = _py_repo(tmp_path, skip=["test-python"])
    config = load_config(repo / "versions.yaml")
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "test-python.yml").write_text("# manual\n")

    # First sync everything else so only test-python would normally drift.
    run(config, workflows_dir=workflows, force=False, check_only=False)
    rc = run(config, workflows_dir=workflows, force=False, check_only=True)
    assert rc == 0
