"""End-to-end tests: run the CLI/runner and verify idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitrera_repo_tools.version_sync.cli import main
from scitrera_repo_tools.version_sync.config import load_config
from scitrera_repo_tools.version_sync.runner import run


def test_end_to_end_idempotent(memorylayer_like: Path) -> None:
    config = load_config(memorylayer_like / "versions.yaml")
    rc1 = run(config, check=False, verbose=False)
    assert rc1 == 0

    rc2 = run(config, check=False, verbose=False)
    assert rc2 == 0

    rc3 = run(config, check=True, verbose=False)
    assert rc3 == 0


def test_end_to_end_via_cli(memorylayer_like: Path, monkeypatch) -> None:
    monkeypatch.chdir(memorylayer_like)
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 0

    # Verify project versions got updated
    sdk_init = (
        memorylayer_like / "memorylayer-sdk-python/src/memorylayer/__init__.py"
    ).read_text()
    assert '__version__ = "0.1.22"' in sdk_init

    plugin = json.loads(
        (memorylayer_like / "memorylayer-cc-plugin/.claude-plugin/plugin.json").read_text()
    )
    assert plugin["version"] == "0.1.22"

    market = json.loads(
        (memorylayer_like / ".claude-plugin/marketplace.json").read_text()
    )
    assert market["plugins"][0]["version"] == "0.1.22"

    # Preferred versions applied
    core_pyproject = (
        memorylayer_like / "memorylayer-core-python/pyproject.toml"
    ).read_text()
    assert '"pydantic==2.13.4"' in core_pyproject
    assert '"fastapi==0.136.1"' in core_pyproject

    cc_pkg = json.loads(
        (memorylayer_like / "memorylayer-cc-plugin/package.json").read_text()
    )
    assert cc_pkg["dependencies"]["@modelcontextprotocol/sdk"] == "^1.26.0"

    # Second run via CLI: clean
    with pytest.raises(SystemExit) as exc_info2:
        main(["--check"])
    assert exc_info2.value.code == 0


def test_cli_check_finds_drift(memorylayer_like: Path, monkeypatch) -> None:
    monkeypatch.chdir(memorylayer_like)
    with pytest.raises(SystemExit) as exc_info:
        main(["--check"])
    assert exc_info.value.code == 1


def test_go_preferred_versions_e2e(tmp_path: Path) -> None:
    """Go monorepo: project version sync + preferred_versions both apply."""
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "go.mod").write_text(
        "module example.com/x/server\n\n"
        "go 1.21\n\n"
        "require (\n"
        "\texample.com/x/api v0.1.0\n"
        "\tgoogle.golang.org/grpc v1.60.0\n"
        "\tgoogle.golang.org/protobuf v1.33.0\n"
        ")\n",
        encoding="utf-8",
    )
    (tmp_path / "server" / "version.go").write_text(
        'package version\n\nconst Version = "0.1.0"\n', encoding="utf-8"
    )

    (tmp_path / "versions.yaml").write_text(
        "x-server: 0.2.0\n"
        "\n"
        "preferred_versions:\n"
        "  go:\n"
        "    \"google.golang.org/grpc\": \"v1.65.0\"\n"
        "    \"google.golang.org/protobuf\": \"1.34.1\"\n"
        "\n"
        "project_rules:\n"
        "  x-server:\n"
        "    - { type: go_version,    path: server/version.go }\n"
        "    - { type: gomod_require, path: server/go.mod, args: [ example.com/x/api ] }\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path / "versions.yaml")
    rc = run(config, check=False, verbose=False)
    assert rc == 0

    gomod = (tmp_path / "server" / "go.mod").read_text()
    # Phase A: gomod_require pinned the internal sibling
    assert "example.com/x/api v0.2.0" in gomod
    # Phase C: preferred_versions normalized + rewrote external pins
    assert "google.golang.org/grpc v1.65.0" in gomod
    assert "google.golang.org/protobuf v1.34.1" in gomod
    # version.go: const Version updated
    version_go = (tmp_path / "server" / "version.go").read_text()
    assert 'const Version = "0.2.0"' in version_go

    # Idempotency
    rc2 = run(config, check=True, verbose=False)
    assert rc2 == 0
