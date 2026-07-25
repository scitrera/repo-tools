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

def test_concurrency_cancels_superseded_runs_only(tmp_path, write_file):
    """Cancel a run the same PR supersedes — not the sibling event of one commit.

    github.ref is stable across pushes to a PR (refs/pull/N/merge), so this still
    collapses rapid successive pushes. It must NOT key on the branch name: that
    would also cancel the push-vs-pull_request pair for a single commit, and a
    cancelled run reports as cancelled rather than success. That duplicate is
    prevented with ci.push_branches instead.
    """
    doc = _doc(tmp_path, write_file, "    lint: none\n")
    assert doc["concurrency"]["group"] == "test-go-${{ github.ref }}"
    assert doc["concurrency"]["cancel-in-progress"] is True


# ── per-project scoping ───────────────────────────────────────────────────────

MULTI = '''\
app: 1.2.3
go_toolchain:
  go: "1.25.12"
project_rules:
  svc:
    - {{ type: gomod_require, path: svc/go.mod }}
  sdk:
    - {{ type: gomod_require, path: sdk/go.mod }}
ci:
  go:
    lint: none
{go_body}
'''


def _multi(tmp_path: Path, write_file, go_body: str):
    write_file(tmp_path / "svc/go.mod", "module example.com/r/svc\n\ngo 1.25\n")
    write_file(tmp_path / "sdk/go.mod", "module example.com/r/sdk\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", MULTI.format(go_body=go_body))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_go(cfg, cfg.ci))


SCOPED = """\
    govulncheck_ignore:
      - id: GO-2026-5668
        reason: "reachable only through the sdk's docker orchestrator"
        projects: [sdk]
"""


def test_scoped_waiver_reaches_only_the_named_project(tmp_path, write_file):
    """A repo-wide waiver would make every other module report it as stale."""
    doc = _multi(tmp_path, write_file, SCOPED)
    assert doc["jobs"]["security-sdk"]["steps"][-1]["env"]["IGNORED_ADVISORIES"] == "GO-2026-5668"
    assert doc["jobs"]["security-svc"]["steps"][-1]["env"]["IGNORED_ADVISORIES"] == ""


def test_unscoped_waiver_still_applies_everywhere(tmp_path, write_file):
    """Omitting `projects` keeps the 0.1.16 behaviour for repo-wide deps."""
    body = SCOPED.replace("        projects: [sdk]\n", "")
    doc = _multi(tmp_path, write_file, body)
    for job in ("security-sdk", "security-svc"):
        assert doc["jobs"][job]["steps"][-1]["env"]["IGNORED_ADVISORIES"] == "GO-2026-5668"


def test_reason_only_rendered_where_the_waiver_applies(tmp_path, write_file):
    write_file(tmp_path / "svc/go.mod", "module example.com/r/svc\n\ngo 1.25\n")
    write_file(tmp_path / "sdk/go.mod", "module example.com/r/sdk\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", MULTI.format(go_body=SCOPED))
    cfg = load_config(tmp_path / "versions.yaml")
    text = build_test_go(cfg, cfg.ci)
    assert text.count("# GO-2026-5668: reachable only through") == 1


def test_unknown_project_in_scope_is_an_error(tmp_path, write_file):
    """A typo would scope the waiver to nothing and fail with no explanation."""
    body = SCOPED.replace("projects: [sdk]", "projects: [sdk-go]")
    with pytest.raises(ValueError, match="unknown Go project"):
        _multi(tmp_path, write_file, body)


def test_empty_projects_list_rejected(tmp_path, write_file):
    body = SCOPED.replace("projects: [sdk]", "projects: []")
    with pytest.raises(ConfigError, match="non-empty list"):
        _multi(tmp_path, write_file, body)


# ── push vs pull_request duplication ──────────────────────────────────────────

def _triggers(doc: dict) -> dict:
    return doc[True]


def test_push_branches_defaults_to_test_branches(tmp_path, write_file):
    """Back-compat: omitting push_branches keeps the previous trigger pair."""
    doc = _doc(tmp_path, write_file, "    lint: none\n")
    on = _triggers(doc)
    assert on["push"]["branches"] == on["pull_request"]["branches"] == ["main", "develop"]


def test_push_branches_narrows_only_the_push_trigger(tmp_path, write_file):
    """The fix for duplicate runs: a PR head branch must not also fire `push`.

    A cancelled run reports as cancelled, never success, and a cancelled
    required check can hold up a merge — so the duplicate has to not exist
    rather than be cancelled after the fact.
    """
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", BODY.format(
        go_body="    lint: none\n").replace("ci:\n", "ci:\n  push_branches: [main]\n"))
    cfg = load_config(tmp_path / "versions.yaml")
    on = _triggers(yaml.safe_load(build_test_go(cfg, cfg.ci)))
    assert on["push"]["branches"] == ["main"]
    assert on["pull_request"]["branches"] == ["main", "develop"]


def test_empty_push_branches_rejected(tmp_path, write_file):
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", BODY.format(
        go_body="    lint: none\n").replace("ci:\n", "ci:\n  push_branches: []\n"))
    with pytest.raises(ConfigError, match="push_branches"):
        load_config(tmp_path / "versions.yaml")
