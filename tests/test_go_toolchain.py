"""Tests for the `go_toolchain` reserved section + Phase E."""

from __future__ import annotations

from pathlib import Path

from scitrera_repo_tools.version_sync.config import load_config
from scitrera_repo_tools.version_sync.runner import run
from scitrera_repo_tools.version_sync.strategies.gomod_directives import (
    update_gomod_go_directive,
    update_gomod_toolchain_directive,
)


def _write_gomod(path: Path, *, go: str = "1.21", toolchain: str | None = "1.21.5") -> None:
    lines = [f"module example.com/x\n\ngo {go}\n"]
    if toolchain is not None:
        lines.append(f"\ntoolchain go{toolchain}\n")
    lines.append("\nrequire google.golang.org/grpc v1.60.0\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_update_go_directive(tmp_path: Path) -> None:
    p = tmp_path / "go.mod"
    _write_gomod(p, go="1.21", toolchain="1.21.5")
    changed, old = update_gomod_go_directive(p, "1.25", dry_run=False)
    assert changed and old == "1.21"
    text = p.read_text()
    assert "\ngo 1.25\n" in text
    assert "toolchain go1.21.5" in text  # toolchain untouched


def test_update_toolchain_directive(tmp_path: Path) -> None:
    p = tmp_path / "go.mod"
    _write_gomod(p, go="1.25", toolchain="1.25.9")
    changed, old = update_gomod_toolchain_directive(p, "1.25.10", dry_run=False)
    assert changed and old == "go1.25.9"
    text = p.read_text()
    assert "toolchain go1.25.10" in text
    assert "go 1.25\n" in text  # `go` directive untouched


def test_update_toolchain_accepts_go_prefix(tmp_path: Path) -> None:
    p = tmp_path / "go.mod"
    _write_gomod(p, go="1.25", toolchain="1.25.9")
    changed, old = update_gomod_toolchain_directive(p, "go1.25.10", dry_run=False)
    assert changed and old == "go1.25.9"
    assert "toolchain go1.25.10" in p.read_text()


def test_update_toolchain_missing_warns(tmp_path: Path, caplog) -> None:
    p = tmp_path / "go.mod"
    _write_gomod(p, go="1.25", toolchain=None)
    changed, old = update_gomod_toolchain_directive(p, "1.25.10", dry_run=False)
    assert not changed and old is None


def test_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "go.mod"
    _write_gomod(p, go="1.25", toolchain="1.25.10")
    changed, _ = update_gomod_go_directive(p, "1.25", dry_run=False)
    assert not changed
    changed, _ = update_gomod_toolchain_directive(p, "1.25.10", dry_run=False)
    assert not changed


def test_go_directive_does_not_match_require_lines(tmp_path: Path) -> None:
    """Critical: the regex must not touch require lines that start with module paths."""
    p = tmp_path / "go.mod"
    p.write_text(
        "module example.com/x\n\n"
        "go 1.25\n\n"
        "require (\n"
        "\tgoogle.golang.org/grpc v1.60.0\n"   # starts with `g`, not `go ` keyword
        "\tgopkg.in/yaml.v3 v3.0.1\n"
        ")\n",
        encoding="utf-8",
    )
    changed, old = update_gomod_go_directive(p, "1.26", dry_run=False)
    assert changed and old == "1.25"
    text = p.read_text()
    assert "google.golang.org/grpc v1.60.0" in text  # untouched
    assert "gopkg.in/yaml.v3 v3.0.1" in text         # untouched
    assert "\ngo 1.26\n" in text


def test_phase_e_through_runner(tmp_path: Path) -> None:
    """End-to-end: go_toolchain section in versions.yaml propagates to every go.mod."""
    (tmp_path / "server").mkdir()
    (tmp_path / "sdk").mkdir()
    _write_gomod(tmp_path / "server" / "go.mod", go="1.21", toolchain="1.21.5")
    _write_gomod(tmp_path / "sdk" / "go.mod", go="1.21", toolchain="1.21.5")

    (tmp_path / "versions.yaml").write_text(
        "x-server: 0.1.0\n"
        "x-sdk: 0.1.0\n"
        "\n"
        "go_toolchain:\n"
        '  go: "1.25"\n'
        '  toolchain: "1.25.10"\n'
        "\n"
        "project_rules:\n"
        "  x-server:\n"
        "    - { type: gomod_require, path: server/go.mod, args: [ google.golang.org/grpc ] }\n"
        "  x-sdk:\n"
        "    - { type: gomod_require, path: sdk/go.mod,    args: [ google.golang.org/grpc ] }\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path / "versions.yaml")
    rc = run(config, check=False, verbose=False)
    assert rc == 0

    for sub in ("server", "sdk"):
        text = (tmp_path / sub / "go.mod").read_text()
        assert "\ngo 1.25\n" in text
        assert "toolchain go1.25.10" in text

    # Idempotent
    assert run(config, check=True, verbose=False) == 0
