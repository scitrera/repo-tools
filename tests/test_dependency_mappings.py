"""Tests for Phase B (dependency_mappings) via runner.run."""

from __future__ import annotations

import json
from pathlib import Path

from scitrera_repo_tools.version_sync.config import load_config
from scitrera_repo_tools.version_sync.runner import run


def test_phase_b_propagates_internal_version(memorylayer_like: Path, caplog) -> None:
    config = load_config(memorylayer_like / "versions.yaml")
    rc = run(config, check=False, verbose=False)
    assert rc == 0

    consumer_pyproject = (
        memorylayer_like / "memorylayer-sdk-langchain-python/pyproject.toml"
    ).read_text()
    assert '"memorylayer-client==0.1.22"' in consumer_pyproject

    consumer_pkg_json = json.loads(
        (memorylayer_like / "memorylayer-cc-plugin/package.json").read_text()
    )
    assert consumer_pkg_json["dependencies"]["@scitrera/memorylayer-mcp-server"] == "0.1.22"


def test_phase_b_check_reports_drift(memorylayer_like: Path) -> None:
    config = load_config(memorylayer_like / "versions.yaml")
    rc = run(config, check=True, verbose=False)
    assert rc == 1


def test_phase_c_skips_phase_b_touched(memorylayer_like: Path) -> None:
    # Add a Phase B and Phase C collision: memorylayer-client is touched by Phase B,
    # so Phase C must not also try to set it (preferred_versions doesn't list it,
    # but pydantic is in preferred_versions for python and must be applied).
    run(load_config(memorylayer_like / "versions.yaml"), check=False, verbose=False)

    sdk_consumer = (
        memorylayer_like / "memorylayer-sdk-langchain-python/pyproject.toml"
    ).read_text()
    assert '"pydantic==2.13.4"' in sdk_consumer
    assert '"memorylayer-client==0.1.22"' in sdk_consumer
