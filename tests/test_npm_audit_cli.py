"""CLI tests for `npm-audit`."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.npm_audit import cli as audit_cli
from scitrera_repo_tools.npm_audit.cli import _build_parser, main


def test_parser_accepts_fix_force_level() -> None:
    p = _build_parser()
    ns = p.parse_args(["--fix", "--force", "--level", "high", "alpha"])
    assert ns.fix is True
    assert ns.force is True
    assert ns.level == "high"
    assert ns.projects == ["alpha"]


def test_parser_rejects_bad_level() -> None:
    p = _build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--level", "bogus"])


def test_parser_no_args() -> None:
    p = _build_parser()
    ns = p.parse_args([])
    assert ns.fix is False
    assert ns.force is False
    assert ns.level is None
    assert ns.projects == []


def _write_minimal_repo(tmp_path: Path) -> Path:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "package.json").write_text(
        '{"name":"alpha","version":"0.0.0"}\n', encoding="utf-8"
    )
    (tmp_path / "alpha" / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "alpha" / "node_modules").mkdir()
    (tmp_path / "versions.yaml").write_text(
        "alpha: 0.1.0\n"
        "project_rules:\n"
        "  alpha:\n"
        "    - { type: package, path: alpha/package.json }\n",
        encoding="utf-8",
    )
    return tmp_path


def test_main_invokes_runner_and_propagates_exit(tmp_path: Path, monkeypatch) -> None:
    _write_minimal_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    captured = {}

    def fake_run(config, *, selected, fix, force, level):
        captured["selected"] = selected
        captured["fix"] = fix
        captured["force"] = force
        captured["level"] = level
        return 0

    monkeypatch.setattr(audit_cli, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        main(["--fix", "alpha"])
    assert exc.value.code == 0
    assert captured == {
        "selected": ["alpha"],
        "fix": True,
        "force": False,
        "level": None,
    }


def test_main_unknown_project_exits_one(tmp_path: Path, monkeypatch) -> None:
    _write_minimal_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        main(["does-not-exist"])
    assert exc.value.code == 1


def test_main_missing_config_exits_two(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audit_cli, "_find_config", lambda _start: None)
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
