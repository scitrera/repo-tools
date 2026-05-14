"""Tests for config.py schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.version_sync.config import ConfigError, load_config


def _write_yaml(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def test_load_minimal(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        "foo-pkg: 1.0.0\nbar-pkg: 0.2.1\n",
    )
    config = load_config(yaml_path)
    assert config.project_versions == {"foo-pkg": "1.0.0", "bar-pkg": "0.2.1"}
    assert config.project_rules == {}
    assert config.preferred_versions.by_language == {}
    assert config.dependency_mappings.packages == {}
    assert config.sources.by_language == {}


def test_rejects_tuple_form(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
foo: 1.0.0
project_rules:
  foo:
    - [ "pyproject", foo/pyproject.toml ]
''',
    )
    with pytest.raises(ConfigError, match="tuple/positional form"):
        load_config(yaml_path)


def test_rejects_invalid_semver(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        "foo: not-a-version\n",
    )
    with pytest.raises(ConfigError, match="Invalid semver"):
        load_config(yaml_path)


def test_project_rules_args_kwargs_roundtrip(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
my-pkg: 1.0.0
project_rules:
  my-pkg:
    - { type: marketplace, path: market.json, args: [my-plugin-dir] }
    - { type: gomod_require, path: go.mod, args: [github.com/x/y], kwargs: { strict: true } }
''',
    )
    config = load_config(yaml_path)
    rules = config.project_rules["my-pkg"]
    assert len(rules) == 2
    assert rules[0].type == "marketplace"
    assert rules[0].args == ("my-plugin-dir",)
    assert rules[0].kwargs == {}
    assert rules[1].args == ("github.com/x/y",)
    assert rules[1].kwargs == {"strict": True}


def test_empty_rules_allowed(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
my-pkg: 1.0.0
project_rules:
  my-pkg: []
''',
    )
    config = load_config(yaml_path)
    assert config.project_rules["my-pkg"] == []


def test_missing_versions_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_preferred_versions_parsed(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
my-pkg: 1.0.0
preferred_versions:
  python:
    "pydantic": "2.13.4"
    "fastapi": ">=0.100"
    "click": null
  typescript:
    "@modelcontextprotocol/sdk": "^1.0.0"
''',
    )
    config = load_config(yaml_path)
    py = config.preferred_versions.for_language("python")
    assert py["pydantic"] == "2.13.4"
    assert py["fastapi"] == ">=0.100"
    assert py["click"] is None
    ts = config.preferred_versions.for_language("typescript")
    assert ts["@modelcontextprotocol/sdk"] == "^1.0.0"


def test_dependency_mappings_parsed(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
inner: 1.0.0
consumer: 1.0.0
dependency_mappings:
  python:
    packages:
      "inner": "inner-published"
    dependencies:
      consumer:
        - "inner"
''',
    )
    config = load_config(yaml_path)
    lang = config.dependency_mappings.language("python")
    assert lang.packages == {"inner": "inner-published"}
    assert lang.dependencies == {"consumer": ["inner"]}


def test_sources_parsed(tmp_path: Path) -> None:
    yaml_path = _write_yaml(
        tmp_path / "versions.yaml",
        '''\
foo: 1.0.0
sources:
  python:
    - "uv.lock"
    - "requirements.txt"
''',
    )
    config = load_config(yaml_path)
    assert config.sources.for_language("python") == ["uv.lock", "requirements.txt"]
