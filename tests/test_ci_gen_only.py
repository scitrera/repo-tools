"""Tests for the ci.only_workflows allowlist."""

from __future__ import annotations

from pathlib import Path

from scitrera_repo_tools.ci_gen_gha.runner import run
from scitrera_repo_tools.version_sync.config import load_config

BODY = '''\
my-py: 0.1.0
my-ts: 0.1.0

project_rules:
  my-py:
    - {{ type: pyproject, path: py/pyproject.toml }}
  my-ts:
    - {{ type: package, path: ts/package.json }}

ci:
{ci_body}
'''


def _cfg(tmp_path: Path, write_file, write_json, ci_body: str):
    write_file(tmp_path / "py/pyproject.toml", '[project]\nname = "my-py"\nversion = "0.1.0"\n')
    write_json(tmp_path / "ts/package.json", {"name": "my-ts", "version": "0.1.0"})
    write_file(tmp_path / "versions.yaml", BODY.format(ci_body=ci_body))
    return load_config(tmp_path / "versions.yaml")


def _generate(tmp_path, write_file, write_json, ci_body: str):
    cfg = _cfg(tmp_path, write_file, write_json, ci_body)
    out = tmp_path / "wf"
    rc = run(cfg, workflows_dir=out, force=False, check_only=False)
    written = sorted(p.name for p in out.glob("*.yml")) if out.exists() else []
    return rc, written


def test_empty_allowlist_manages_everything(tmp_path, write_file, write_json):
    rc, written = _generate(tmp_path, write_file, write_json, "  test_branches: [main]\n")
    assert rc == 0
    assert written == [
        "publish-npm.yml", "publish-python.yml",
        "test-npm.yml", "test-python.yml", "version-check.yml",
    ]


def test_allowlist_restricts_to_named_workflows(tmp_path, write_file, write_json):
    rc, written = _generate(
        tmp_path, write_file, write_json, "  only_workflows: [version-check]\n"
    )
    assert rc == 0
    assert written == ["version-check.yml"]


def test_allowlist_accepts_several(tmp_path, write_file, write_json):
    rc, written = _generate(
        tmp_path, write_file, write_json,
        "  only_workflows: [version-check, test-python]\n",
    )
    assert rc == 0
    assert written == ["test-python.yml", "version-check.yml"]


def test_unknown_name_is_an_error_not_an_empty_selection(tmp_path, write_file, write_json):
    """A typo must fail loudly; managing nothing would otherwise look like success."""
    rc, written = _generate(
        tmp_path, write_file, write_json, "  only_workflows: [verison-check]\n"
    )
    assert rc == 2
    assert written == []


def test_allowlisting_a_workflow_with_no_projects_writes_nothing(
    tmp_path, write_file, write_json
):
    """test-go renders empty here (no Go projects) — selecting it is a no-op."""
    rc, written = _generate(tmp_path, write_file, write_json, "  only_workflows: [test-go]\n")
    assert rc == 0
    assert written == []


def test_skip_still_subtracts_from_the_allowlist(tmp_path, write_file, write_json):
    rc, written = _generate(
        tmp_path, write_file, write_json,
        "  only_workflows: [version-check, test-python]\n"
        "  skip_workflows: [test-python]\n",
    )
    assert rc == 0
    assert written == ["version-check.yml"]


def test_excluded_workflows_are_reported(tmp_path, write_file, write_json, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="scitrera_repo_tools.ci_gen_gha")
    _generate(tmp_path, write_file, write_json, "  only_workflows: [version-check]\n")
    text = caplog.text
    assert "not in ci.only_workflows" in text
    assert "test-python.yml" in text
    # Workflows that render empty are not noise-listed.
    assert "test-go.yml" not in text


def test_allowlist_is_honored_under_check(tmp_path, write_file, write_json):
    cfg = _cfg(tmp_path, write_file, write_json, "  only_workflows: [version-check]\n")
    out = tmp_path / "wf"
    # Only the allowlisted workflow is missing, so exactly one drives the exit.
    assert run(cfg, workflows_dir=out, force=False, check_only=True) == 1
    assert not out.exists() or sorted(p.name for p in out.glob("*.yml")) == []
