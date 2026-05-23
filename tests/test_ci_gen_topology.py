"""Topology resolver: leaves-first toposort with alphabetical tie-breaks."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.ci_gen_gha.topology import publish_order
from scitrera_repo_tools.version_sync.config import load_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    (tmp_path / "versions.yaml").write_text(body, encoding="utf-8")
    # Generators don't actually read the manifest files, but discovery resolves
    # paths relative to root; create empty placeholders for any rules.
    return tmp_path


def test_two_projects_with_one_dep(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "alpha: 0.1.0\n"
        "beta: 0.1.0\n"
        "project_rules:\n"
        "  alpha:\n"
        "    - { type: package, path: alpha/package.json }\n"
        "  beta:\n"
        "    - { type: package, path: beta/package.json }\n"
        "dependency_mappings:\n"
        "  typescript:\n"
        "    packages:\n"
        "      alpha: '@scope/alpha'\n"
        "    dependencies:\n"
        "      beta:\n"
        "        - alpha\n",
    )

    config = load_config(tmp_path / "versions.yaml")
    order = publish_order(config, "typescript")
    names = [n.name for n in order]
    assert names == ["alpha", "beta"]
    assert order[0].needs == ()
    assert order[1].needs == ("alpha",)


def test_independent_projects_alphabetical(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "zeta: 0.1.0\n"
        "alpha: 0.1.0\n"
        "mu: 0.1.0\n"
        "project_rules:\n"
        "  zeta:\n"
        "    - { type: pyproject, path: zeta/pyproject.toml }\n"
        "  alpha:\n"
        "    - { type: pyproject, path: alpha/pyproject.toml }\n"
        "  mu:\n"
        "    - { type: pyproject, path: mu/pyproject.toml }\n",
    )

    config = load_config(tmp_path / "versions.yaml")
    order = publish_order(config, "python")
    assert [n.name for n in order] == ["alpha", "mu", "zeta"]
    assert all(n.needs == () for n in order)


def test_diamond_dep(tmp_path: Path) -> None:
    """a → b, a → c, both → d. Order must respect every edge."""
    _write_yaml(
        tmp_path,
        "a: 0.1.0\nb: 0.1.0\nc: 0.1.0\nd: 0.1.0\n"
        "project_rules:\n"
        "  a: [{ type: pyproject, path: a/pyproject.toml }]\n"
        "  b: [{ type: pyproject, path: b/pyproject.toml }]\n"
        "  c: [{ type: pyproject, path: c/pyproject.toml }]\n"
        "  d: [{ type: pyproject, path: d/pyproject.toml }]\n"
        "dependency_mappings:\n"
        "  python:\n"
        "    packages:\n"
        "      a: aa\n"
        "      b: bb\n"
        "      c: cc\n"
        "    dependencies:\n"
        "      b: [a]\n"
        "      c: [a]\n"
        "      d: [b, c]\n",
    )

    config = load_config(tmp_path / "versions.yaml")
    order = publish_order(config, "python")
    names = [n.name for n in order]
    pos = {name: i for i, name in enumerate(names)}
    assert pos["a"] < pos["b"]
    assert pos["a"] < pos["c"]
    assert pos["b"] < pos["d"]
    assert pos["c"] < pos["d"]


def test_cycle_detection(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "a: 0.1.0\nb: 0.1.0\n"
        "project_rules:\n"
        "  a: [{ type: pyproject, path: a/pyproject.toml }]\n"
        "  b: [{ type: pyproject, path: b/pyproject.toml }]\n"
        "dependency_mappings:\n"
        "  python:\n"
        "    packages:\n"
        "      a: aa\n"
        "      b: bb\n"
        "    dependencies:\n"
        "      a: [b]\n"
        "      b: [a]\n",
    )

    config = load_config(tmp_path / "versions.yaml")
    with pytest.raises(ValueError, match="Cyclic publish dependency"):
        publish_order(config, "python")


def test_no_projects_returns_empty(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "a: 0.1.0\nproject_rules:\n  a: []\n")
    config = load_config(tmp_path / "versions.yaml")
    assert publish_order(config, "python") == []
    assert publish_order(config, "typescript") == []


def test_dep_outside_publishable_set_is_ignored(tmp_path: Path) -> None:
    """If a dependency entry references a non-publishable project, skip it."""
    _write_yaml(
        tmp_path,
        "consumer: 0.1.0\nproject_rules:\n"
        "  consumer:\n"
        "    - { type: pyproject, path: consumer/pyproject.toml }\n"
        "dependency_mappings:\n"
        "  python:\n"
        "    packages:\n"
        "      external: external\n"
        "    dependencies:\n"
        "      consumer: [external]\n",
    )

    config = load_config(tmp_path / "versions.yaml")
    order = publish_order(config, "python")
    assert [n.name for n in order] == ["consumer"]
    assert order[0].needs == ()
