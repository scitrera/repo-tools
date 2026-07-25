"""Tests for the govulncheck allow-list and duplicate-run suppression."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_test_go
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

BODY = '''\
app: 1.2.3

go_toolchain:
  go: "1.25.12"

project_rules:
  app:
    - {{ type: gomod_require, path: go.mod }}

ci:
  go:
{go_body}
'''


def _doc(tmp_path: Path, write_file, go_body: str) -> dict:
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", BODY.format(go_body=go_body))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_go(cfg, cfg.ci))


def _security(doc: dict) -> dict:
    return doc["jobs"]["security-app"]["steps"][-1]


IGNORE = """\
    govulncheck_ignore:
      - id: GO-2026-5668
        reason: "docker/docker; no upstream fix"
"""


def test_govulncheck_version_is_pinned_by_default(tmp_path, write_file):
    """An unpinned scanner turns an upstream release into a red unrelated PR."""
    doc = _doc(tmp_path, write_file, "    lint: none\n")
    install = doc["jobs"]["security-app"]["steps"][-2]["run"]
    assert "govulncheck@v1.1.4" in install
    assert "@latest" not in install


def test_no_allow_list_still_runs_the_scan(tmp_path, write_file):
    step = _security(_doc(tmp_path, write_file, "    lint: none\n"))
    assert step["env"]["IGNORED_ADVISORIES"] == ""
    assert "govulncheck -format json ./..." in step["run"]


def test_allow_listed_ids_reach_the_job(tmp_path, write_file):
    step = _security(_doc(tmp_path, write_file, IGNORE))
    assert step["env"]["IGNORED_ADVISORIES"] == "GO-2026-5668"


def test_reason_is_recorded_next_to_the_id(tmp_path, write_file):
    """A waiver is a security decision; the workflow should say why.

    The reason is emitted as a YAML comment beside the id, so it is asserted
    against the rendered text — parsing discards comments.
    """
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", BODY.format(go_body=IGNORE))
    cfg = load_config(tmp_path / "versions.yaml")
    text = build_test_go(cfg, cfg.ci)
    assert "# GO-2026-5668: docker/docker; no upstream fix" in text


def test_scan_is_not_blanket_non_blocking(tmp_path, write_file):
    """continue-on-error would hide new advisories too — the point is not to."""
    job = _doc(tmp_path, write_file, IGNORE)["jobs"]["security-app"]
    assert "continue-on-error" not in yaml.dump(job)
    assert "not allow-listed" in _security(_doc(tmp_path, write_file, IGNORE))["run"]


def test_stale_allow_list_entries_are_reported(tmp_path, write_file):
    run = _security(_doc(tmp_path, write_file, IGNORE))["run"]
    assert "no longer reachable" in run


def test_only_called_findings_gate_the_build(tmp_path, write_file):
    """Advisories present but unreachable are not a vuln in this binary."""
    run = _security(_doc(tmp_path, write_file, IGNORE))["run"]
    assert ".trace[0].function" in run


def test_empty_report_fails_rather_than_passing_silently(tmp_path, write_file):
    run = _security(_doc(tmp_path, write_file, IGNORE))["run"]
    assert "produced no output" in run


def test_ignore_entry_requires_a_reason(tmp_path, write_file):
    body = "    govulncheck_ignore:\n      - id: GO-2026-5668\n"
    with pytest.raises(ConfigError, match="reason"):
        _doc(tmp_path, write_file, body)


def test_ignore_entry_requires_an_id(tmp_path, write_file):
    body = '    govulncheck_ignore:\n      - reason: "no id here"\n'
    with pytest.raises(ConfigError, match="id"):
        _doc(tmp_path, write_file, body)


def test_ignore_entry_rejects_unknown_keys(tmp_path, write_file):
    body = (
        "    govulncheck_ignore:\n      - id: GO-1\n"
        '        reason: "r"\n        expires: 2030-01-01\n'
    )
    with pytest.raises(ConfigError, match="unknown key"):
        _doc(tmp_path, write_file, body)


# ── duplicate-run suppression ─────────────────────────────────────────────────

def test_concurrency_collapses_push_and_pr_runs(tmp_path, write_file):
    """Pushing to a branch with an open PR fires both events.

    github.ref differs between them, so keying on it leaves two full runs. Keying
    on the branch name makes them share a group and cancel down to one.
    """
    doc = _doc(tmp_path, write_file, "    lint: none\n")
    group = doc["concurrency"]["group"]
    assert group == "test-go-${{ github.head_ref || github.ref_name }}"
    assert doc["concurrency"]["cancel-in-progress"] is True
