"""ci.npm.setup_steps / extra_steps — parity with the python side."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_test_npm
from scitrera_repo_tools.version_sync.config import ConfigError, load_config


def _build(tmp_path: Path, ci_block: str) -> dict:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps({"name": "@acme/web", "version": "0.0.1"}), encoding="utf-8"
    )
    (tmp_path / "versions.yaml").write_text(
        "web: 0.0.1\n"
        "project_rules:\n"
        "  web:\n"
        "    - { type: package, path: web/package.json }\n"
        f"{ci_block}",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_npm(config, config.ci))


def _step_names(doc: dict) -> list:
    return [s.get("name") for s in doc["jobs"]["test-web"]["steps"]]


def test_setup_steps_run_before_install(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "ci:\n"
        "  npm:\n"
        "    setup_steps:\n"
        "      - { name: Free disk, run: 'df -h' }\n",
    )
    names = _step_names(doc)
    assert names.index("Free disk") < names.index("Install")


def test_extra_steps_run_after_the_tests(tmp_path: Path) -> None:
    """Where a check on build output belongs — the build has happened by then."""
    doc = _build(
        tmp_path,
        "ci:\n"
        "  npm:\n"
        "    build: true\n"
        "    extra_steps:\n"
        "      - { name: Verify generated assets, run: 'git diff --exit-code' }\n",
    )
    names = _step_names(doc)
    assert names.index("Verify generated assets") > names.index("Run tests")


def test_step_defaults_to_the_project_directory(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "ci:\n  npm:\n    extra_steps:\n      - { name: Check, run: 'ls' }\n",
    )
    step = next(s for s in doc["jobs"]["test-web"]["steps"] if s.get("name") == "Check")
    assert step["working-directory"] == "web"


def test_working_directory_can_escape_the_project(tmp_path: Path) -> None:
    """A committed asset built by the frontend lives outside the npm package."""
    doc = _build(
        tmp_path,
        "ci:\n"
        "  npm:\n"
        "    extra_steps:\n"
        "      - name: Check\n"
        "        run: 'git diff --exit-code -- pkg/admin/ui'\n"
        "        working_directory: '.'\n",
    )
    step = next(s for s in doc["jobs"]["test-web"]["steps"] if s.get("name") == "Check")
    assert step["working-directory"] == "."


def test_no_steps_leaves_the_job_unchanged(tmp_path: Path) -> None:
    doc = _build(tmp_path, "")
    assert _step_names(doc) == [None, None, "Install", "Type-check", "Run tests"]


def test_malformed_step_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ci.npm.extra_steps"):
        _build(
            tmp_path,
            "ci:\n  npm:\n    extra_steps:\n      - { name: '', run: 'x' }\n",
        )
