"""End-to-end tests: run the CLI/runner and verify idempotency."""

from __future__ import annotations

import json
import os
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
