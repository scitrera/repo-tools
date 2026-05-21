"""Runner tests for `npm-audit` with subprocess.run faked."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

from scitrera_repo_tools.npm_audit.runner import run
from scitrera_repo_tools.version_sync.config import load_config


@dataclass
class _Call:
    cmd: List[str]
    cwd: str


@dataclass
class _FakeNpm:
    """Records every `subprocess.run` call and returns scripted exit codes."""
    audit_returncode: int = 0
    audit_fix_returncode: int = 0
    ci_returncode: int = 0
    calls: List[_Call] = field(default_factory=list)

    def __call__(self, cmd, cwd, check):
        assert isinstance(cmd, list)
        assert check is False, "runner must not raise on non-zero exits"
        self.calls.append(_Call(cmd=cmd, cwd=cwd))

        if cmd[:2] == ["npm", "ci"]:
            rc = self.ci_returncode
        elif cmd[:3] == ["npm", "audit", "fix"]:
            rc = self.audit_fix_returncode
        elif cmd[:2] == ["npm", "audit"]:
            rc = self.audit_returncode
        else:
            raise AssertionError(f"unexpected command: {cmd!r}")
        return subprocess.CompletedProcess(args=cmd, returncode=rc)


@pytest.fixture
def ts_only_repo(tmp_path: Path) -> Path:
    """Two TS projects with pre-existing lockfiles + node_modules."""
    for proj in ("alpha", "beta"):
        d = tmp_path / proj
        d.mkdir()
        (d / "package.json").write_text(
            '{"name":"@scope/' + proj + '","version":"0.0.0"}\n', encoding="utf-8"
        )
        (d / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (d / "node_modules").mkdir()

    (tmp_path / "versions.yaml").write_text(
        "alpha: 0.1.0\n"
        "beta: 0.1.0\n"
        "\n"
        "project_rules:\n"
        "  alpha:\n"
        "    - { type: package, path: alpha/package.json }\n"
        "  beta:\n"
        "    - { type: package, path: beta/package.json }\n",
        encoding="utf-8",
    )
    return tmp_path


def _load(repo: Path):
    return load_config(repo / "versions.yaml")


def test_clean_audit_exits_zero(ts_only_repo: Path) -> None:
    fake = _FakeNpm()
    rc = run(
        _load(ts_only_repo),
        selected=None, fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 0
    audit_calls = [c for c in fake.calls if c.cmd[:2] == ["npm", "audit"]]
    assert [Path(c.cwd).name for c in audit_calls] == ["alpha", "beta"]


def test_audit_failure_propagates_exit_one(ts_only_repo: Path) -> None:
    fake = _FakeNpm(audit_returncode=1)
    rc = run(
        _load(ts_only_repo),
        selected=None, fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 1


def test_missing_lockfile_skips_audit(ts_only_repo: Path) -> None:
    (ts_only_repo / "alpha" / "package-lock.json").unlink()
    fake = _FakeNpm()
    rc = run(
        _load(ts_only_repo),
        selected=None, fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 1
    alpha_calls = [c for c in fake.calls if Path(c.cwd).name == "alpha"]
    assert alpha_calls == []
    beta_audits = [
        c for c in fake.calls
        if Path(c.cwd).name == "beta" and c.cmd[:2] == ["npm", "audit"]
    ]
    assert len(beta_audits) == 1


def test_fix_runs_before_audit(ts_only_repo: Path) -> None:
    fake = _FakeNpm()
    rc = run(
        _load(ts_only_repo),
        selected=["alpha"], fix=True, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 0
    alpha_calls = [c for c in fake.calls if Path(c.cwd).name == "alpha"]
    cmds = [c.cmd[:3] for c in alpha_calls]
    assert cmds == [["npm", "audit", "fix"], ["npm", "audit"]]


def test_fix_force_passes_force_flag(ts_only_repo: Path) -> None:
    fake = _FakeNpm()
    run(
        _load(ts_only_repo),
        selected=["alpha"], fix=True, force=True, level=None,
        use_color=False, runner=fake,
    )
    fix_call = next(c for c in fake.calls if c.cmd[:3] == ["npm", "audit", "fix"])
    assert "--force" in fix_call.cmd


def test_level_flag_propagated(ts_only_repo: Path) -> None:
    fake = _FakeNpm()
    run(
        _load(ts_only_repo),
        selected=["alpha"], fix=True, force=False, level="high",
        use_color=False, runner=fake,
    )
    for c in fake.calls:
        if c.cmd[:2] == ["npm", "audit"]:
            assert c.cmd[-2:] == ["--audit-level", "high"]


def test_npm_ci_runs_when_node_modules_missing(ts_only_repo: Path) -> None:
    import shutil
    shutil.rmtree(ts_only_repo / "alpha" / "node_modules")
    fake = _FakeNpm()
    rc = run(
        _load(ts_only_repo),
        selected=["alpha"], fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 0
    assert any(c.cmd[:2] == ["npm", "ci"] for c in fake.calls)


def test_npm_ci_failure_skips_audit(ts_only_repo: Path) -> None:
    import shutil
    shutil.rmtree(ts_only_repo / "alpha" / "node_modules")
    fake = _FakeNpm(ci_returncode=1)
    rc = run(
        _load(ts_only_repo),
        selected=["alpha"], fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 1
    audit_after_failed_ci = [c for c in fake.calls if c.cmd[:2] == ["npm", "audit"]]
    assert audit_after_failed_ci == []


def test_unknown_project_exits_one_without_subprocess(ts_only_repo: Path) -> None:
    fake = _FakeNpm()
    rc = run(
        _load(ts_only_repo),
        selected=["does-not-exist"], fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 1
    assert fake.calls == []


def test_no_typescript_projects_returns_zero(tmp_path: Path) -> None:
    (tmp_path / "versions.yaml").write_text(
        "foo: 0.1.0\n"
        "project_rules:\n"
        "  foo: []\n",
        encoding="utf-8",
    )
    fake = _FakeNpm()
    rc = run(
        load_config(tmp_path / "versions.yaml"),
        selected=None, fix=False, force=False, level=None,
        use_color=False, runner=fake,
    )
    assert rc == 0
    assert fake.calls == []
