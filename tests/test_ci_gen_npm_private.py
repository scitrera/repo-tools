"""A `"private": true` package is tested but never published."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_npm, build_test_npm
from scitrera_repo_tools.version_sync.config import load_config


def _repo(tmp_path: Path, *, private_web: bool = True, extra_ci: str = "") -> Path:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps(
            {
                "name": "@acme/web",
                "version": "0.0.1",
                **({"private": True} if private_web else {}),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "sdk").mkdir()
    (tmp_path / "sdk" / "package.json").write_text(
        json.dumps({"name": "@acme/sdk", "version": "0.0.1"}), encoding="utf-8"
    )
    (tmp_path / "versions.yaml").write_text(
        "web: 0.0.1\n"
        "sdk: 0.0.1\n"
        "project_rules:\n"
        "  web:\n"
        "    - { type: package, path: web/package.json }\n"
        "  sdk:\n"
        "    - { type: package, path: sdk/package.json }\n"
        f"{extra_ci}",
        encoding="utf-8",
    )
    return tmp_path


def test_private_package_gets_no_publish_job(tmp_path: Path) -> None:
    config = load_config(_repo(tmp_path) / "versions.yaml")
    doc = yaml.safe_load(build_publish_npm(config, config.ci))
    assert "publish-sdk" in doc["jobs"]
    assert "publish-web" not in doc["jobs"]


def test_private_package_is_still_tested(tmp_path: Path) -> None:
    """Private only means "not for the registry"; the code still needs a suite."""
    config = load_config(_repo(tmp_path) / "versions.yaml")
    doc = yaml.safe_load(build_test_npm(config, config.ci))
    assert {"test-web", "test-sdk"} <= set(doc["jobs"])


def test_publishable_package_is_unaffected(tmp_path: Path) -> None:
    config = load_config(_repo(tmp_path, private_web=False) / "versions.yaml")
    doc = yaml.safe_load(build_publish_npm(config, config.ci))
    assert {"publish-web", "publish-sdk"} <= set(doc["jobs"])


def test_naming_a_private_package_to_publish_is_an_error(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        extra_ci="ci:\n  npm:\n    publish_projects: [ web, sdk ]\n",
    )
    config = load_config(root / "versions.yaml")
    with pytest.raises(ValueError, match='"private": true'):
        build_publish_npm(config, config.ci)


def test_all_private_renders_no_workflow(tmp_path: Path) -> None:
    """The only TS project being private means there is nothing to publish."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps({"name": "@acme/web", "version": "0.0.1", "private": True}),
        encoding="utf-8",
    )
    (tmp_path / "versions.yaml").write_text(
        "web: 0.0.1\n"
        "project_rules:\n"
        "  web:\n"
        "    - { type: package, path: web/package.json }\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    assert build_publish_npm(config, config.ci) == ""


def test_private_dependency_edge_is_pruned(tmp_path: Path) -> None:
    """A dependent must not `needs:` a job that was never rendered."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text(
        json.dumps({"name": "@acme/web", "version": "0.0.1", "private": True}),
        encoding="utf-8",
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text(
        json.dumps(
            {"name": "@acme/app", "version": "0.0.1", "dependencies": {"@acme/web": "0.0.1"}}
        ),
        encoding="utf-8",
    )
    (tmp_path / "versions.yaml").write_text(
        "web: 0.0.1\n"
        "app: 0.0.1\n"
        "project_rules:\n"
        "  web:\n"
        "    - { type: package, path: web/package.json }\n"
        "  app:\n"
        "    - { type: package, path: app/package.json }\n"
        "dependency_mappings:\n"
        "  typescript:\n"
        "    packages:\n"
        '      "web": "@acme/web"\n'
        "    dependencies:\n"
        "      app:\n"
        '        - "web"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_publish_npm(config, config.ci))
    assert "publish-web" not in doc["jobs"]
    assert "publish-app" in doc["jobs"]
    assert "publish-web" not in str(doc["jobs"]["publish-app"].get("needs", []))
