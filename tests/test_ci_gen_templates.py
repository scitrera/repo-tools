"""Template renderers: check key invariants without snapshotting full YAML."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import (
    build_publish_npm,
    build_publish_python,
    build_test_npm,
    build_test_python,
    build_version_check,
    render_all,
)
from scitrera_repo_tools.version_sync.config import load_config


@pytest.fixture
def small_repo(tmp_path: Path) -> Path:
    (tmp_path / "py-a").mkdir()
    (tmp_path / "py-a" / "pyproject.toml").write_text("[project]\nname='py-a'\nversion='0.0.0'\n")
    (tmp_path / "py-b").mkdir()
    (tmp_path / "py-b" / "pyproject.toml").write_text("[project]\nname='py-b'\nversion='0.0.0'\n")
    (tmp_path / "ts-a").mkdir()
    (tmp_path / "ts-a" / "package.json").write_text('{"name":"ts-a","version":"0.0.0"}\n')

    (tmp_path / "versions.yaml").write_text(
        "py-a: 0.1.0\npy-b: 0.1.0\nts-a: 0.1.0\n"
        "project_rules:\n"
        "  py-a: [{ type: pyproject, path: py-a/pyproject.toml }]\n"
        "  py-b: [{ type: pyproject, path: py-b/pyproject.toml }]\n"
        "  ts-a: [{ type: package, path: ts-a/package.json }]\n"
        "dependency_mappings:\n"
        "  python:\n"
        "    packages:\n"
        "      py-a: pyA\n"
        "    dependencies:\n"
        "      py-b: [py-a]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_all_templates_parse_as_yaml(small_repo: Path) -> None:
    """Every non-empty rendered workflow must be valid YAML."""
    config = load_config(small_repo / "versions.yaml")
    for filename, text in render_all(config).items():
        if not text:
            continue
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise AssertionError(f"{filename} is not valid YAML: {exc}") from exc


def test_version_check_paths_filter(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_version_check(config, config.ci)
    parsed = yaml.safe_load(text)

    paths = parsed[True]["pull_request"]["paths"]
    assert "versions.yaml" in paths
    assert "py-a/pyproject.toml" in paths
    assert "py-b/pyproject.toml" in paths
    assert "ts-a/package.json" in paths


def test_test_python_per_project_job_with_matrix(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_test_python(config, config.ci)
    parsed = yaml.safe_load(text)

    jobs = parsed["jobs"]
    assert set(jobs) == {"test-py-a", "test-py-b"}
    assert jobs["test-py-a"]["strategy"]["matrix"]["python-version"] == [
        "3.11", "3.12", "3.13",
    ]


def test_test_python_respects_test_branches(tmp_path: Path) -> None:
    (tmp_path / "pyproj").mkdir()
    (tmp_path / "pyproj" / "pyproject.toml").write_text("[project]\nversion='0.0.0'\n")
    (tmp_path / "versions.yaml").write_text(
        "p: 0.1.0\n"
        "project_rules:\n"
        "  p: [{ type: pyproject, path: pyproj/pyproject.toml }]\n"
        "ci:\n"
        "  test_branches: [main]\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path / "versions.yaml")
    text = build_test_python(config, config.ci)
    parsed = yaml.safe_load(text)
    assert parsed[True]["push"]["branches"] == ["main"]
    assert parsed[True]["pull_request"]["branches"] == ["main"]


def test_test_python_lint_step_added_when_ruff(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_test_python(config, config.ci)
    assert "ruff check" in text


def test_test_python_lint_omitted_when_none(tmp_path: Path) -> None:
    (tmp_path / "pyproj").mkdir()
    (tmp_path / "pyproj" / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "versions.yaml").write_text(
        "p: 0.1.0\n"
        "project_rules:\n"
        "  p: [{ type: pyproject, path: pyproj/pyproject.toml }]\n"
        "ci:\n"
        "  python:\n"
        "    lint: none\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    text = build_test_python(config, config.ci)
    assert "ruff check" not in text


def test_test_npm_per_project_job(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_test_npm(config, config.ci)
    parsed = yaml.safe_load(text)
    assert set(parsed["jobs"]) == {"test-ts-a"}


def test_publish_python_topo_needs_chain(small_repo: Path) -> None:
    """Dependents publish after their dependencies, and both wait on the gates."""
    config = load_config(small_repo / "versions.yaml")
    text = build_publish_python(config, config.ci)
    parsed = yaml.safe_load(text)

    jobs = parsed["jobs"]
    gates = ["tests"]
    assert jobs["publish-py-a"]["needs"] == gates
    assert jobs["publish-py-b"]["needs"] == gates + ["publish-py-a"]


def test_publish_python_release_step_present(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_publish_python(config, config.ci)
    assert "sync-versions --release" in text


def test_publish_npm_token_env_default(small_repo: Path) -> None:
    config = load_config(small_repo / "versions.yaml")
    text = build_publish_npm(config, config.ci)
    assert "NPM_TOKEN" in text
    assert "--provenance" not in text


def test_publish_npm_provenance_flag(tmp_path: Path) -> None:
    (tmp_path / "ts").mkdir()
    (tmp_path / "ts" / "package.json").write_text('{"name":"t","version":"0.0.0"}')
    (tmp_path / "versions.yaml").write_text(
        "t: 0.1.0\n"
        "project_rules:\n"
        "  t: [{ type: package, path: ts/package.json }]\n"
        "ci:\n"
        "  npm:\n"
        "    use_provenance: true\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    text = build_publish_npm(config, config.ci)
    assert "--provenance" in text


def test_publish_npm_oidc_skips_token(tmp_path: Path) -> None:
    (tmp_path / "ts").mkdir()
    (tmp_path / "ts" / "package.json").write_text('{"name":"t","version":"0.0.0"}')
    (tmp_path / "versions.yaml").write_text(
        "t: 0.1.0\n"
        "project_rules:\n"
        "  t: [{ type: package, path: ts/package.json }]\n"
        "ci:\n"
        "  npm:\n"
        "    use_oidc: true\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    text = build_publish_npm(config, config.ci)
    assert "NPM_TOKEN" not in text


def test_empty_lang_yields_empty_string(tmp_path: Path) -> None:
    """No python projects → build_test_python returns empty string."""
    (tmp_path / "ts").mkdir()
    (tmp_path / "ts" / "package.json").write_text('{"name":"t","version":"0.0.0"}')
    (tmp_path / "versions.yaml").write_text(
        "t: 0.1.0\n"
        "project_rules:\n"
        "  t: [{ type: package, path: ts/package.json }]\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    assert build_test_python(config, config.ci) == ""
    assert build_publish_python(config, config.ci) == ""
    assert build_test_npm(config, config.ci) != ""
