"""Go test workflow generator."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_test_go
from scitrera_repo_tools.version_sync.config import load_config


@pytest.fixture
def go_repo(tmp_path: Path) -> Path:
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "go.mod").write_text("module x\n")
    (tmp_path / "server" / "go.sum").write_text("")
    (tmp_path / "sdk-go").mkdir()
    (tmp_path / "sdk-go" / "go.mod").write_text("module y\n")
    (tmp_path / "sdk-go" / "go.sum").write_text("")
    (tmp_path / "versions.yaml").write_text(
        "gateway: 0.1.0\nsdk-go: 0.1.0\n"
        "go_toolchain:\n  go: '1.25.10'\n"
        "project_rules:\n"
        "  gateway:\n"
        "    - { type: gomod_require, path: server/go.mod, args: [ x/y ] }\n"
        "  sdk-go:\n"
        "    - { type: gomod_require, path: sdk-go/go.mod, args: [ x/y ] }\n",
        encoding="utf-8",
    )
    return tmp_path


def test_per_project_jobs(go_repo: Path) -> None:
    config = load_config(go_repo / "versions.yaml")
    text = build_test_go(config, config.ci)
    parsed = yaml.safe_load(text)
    job_ids = set(parsed["jobs"])
    # Default: test + lint + security per project.
    assert {"test-gateway", "test-sdk-go", "lint-gateway", "lint-sdk-go",
            "security-gateway", "security-sdk-go"} <= job_ids


def test_go_version_from_toolchain(go_repo: Path) -> None:
    config = load_config(go_repo / "versions.yaml")
    text = build_test_go(config, config.ci)
    assert "go-version: '1.25.10'" in text


def test_ci_go_overrides_toolchain(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "go.mod").write_text("module a\n")
    (tmp_path / "x" / "go.sum").write_text("")
    (tmp_path / "versions.yaml").write_text(
        "x: 0.1.0\n"
        "go_toolchain:\n  go: '1.24.0'\n"
        "project_rules:\n"
        "  x:\n"
        "    - { type: gomod_require, path: x/go.mod, args: [ a ] }\n"
        "ci:\n  go:\n    go_version: '1.26.0'\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    text = build_test_go(config, config.ci)
    assert "go-version: '1.26.0'" in text
    assert "1.24.0" not in text


def test_lint_omitted_when_none(go_repo: Path, tmp_path_factory) -> None:
    # Reuse fixture but override lint
    (go_repo / "versions.yaml").write_text(
        (go_repo / "versions.yaml").read_text() + "ci:\n  go:\n    lint: none\n",
        encoding="utf-8",
    )
    config = load_config(go_repo / "versions.yaml")
    text = build_test_go(config, config.ci)
    parsed = yaml.safe_load(text)
    assert not any(j.startswith("lint-") for j in parsed["jobs"])


def test_govulncheck_omitted_when_disabled(go_repo: Path) -> None:
    (go_repo / "versions.yaml").write_text(
        (go_repo / "versions.yaml").read_text()
        + "ci:\n  go:\n    enable_govulncheck: false\n",
        encoding="utf-8",
    )
    config = load_config(go_repo / "versions.yaml")
    text = build_test_go(config, config.ci)
    parsed = yaml.safe_load(text)
    assert not any(j.startswith("security-") for j in parsed["jobs"])


def test_cache_dep_path_per_project(go_repo: Path) -> None:
    config = load_config(go_repo / "versions.yaml")
    text = build_test_go(config, config.ci)
    assert "cache-dependency-path: server/go.sum" in text
    assert "cache-dependency-path: sdk-go/go.sum" in text


def test_empty_when_no_go_projects(tmp_path: Path) -> None:
    (tmp_path / "versions.yaml").write_text(
        "py: 0.1.0\nproject_rules:\n  py:\n    - { type: pyproject, path: pyproject.toml }\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    assert build_test_go(config, config.ci) == ""
