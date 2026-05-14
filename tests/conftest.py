"""Shared pytest fixtures for scitrera-repo-tools tests."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def write_file():
    def _write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content), encoding="utf-8")
        return path
    return _write


@pytest.fixture
def write_json():
    def _write(path: Path, data) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path
    return _write


@pytest.fixture
def memorylayer_like(tmp_path: Path, write_file, write_json) -> Path:
    """Mini-monorepo mirroring the memorylayer/oss structure (Phase A/B/C smoke)."""
    root = tmp_path / "oss"
    root.mkdir()

    # Top-level marketplace.json
    write_json(
        root / ".claude-plugin/marketplace.json",
        {
            "plugins": [
                {"source": "memorylayer-cc-plugin", "version": "0.0.0"},
            ],
        },
    )

    # memorylayer-core-python
    write_file(
        root / "memorylayer-core-python/pyproject.toml",
        '''\
        [project]
        name = "memorylayer-core-python"
        version = "0.0.0"
        dependencies = [
            "pydantic>=2.0",
            "fastapi==0.100.0",
        ]
        ''',
    )
    write_file(
        root / "memorylayer-core-python/src/memorylayer_server/__init__.py",
        '__version__ = "0.0.0"\n',
    )

    # memorylayer-sdk-python (the internal source-of-truth for memorylayer-client)
    write_file(
        root / "memorylayer-sdk-python/pyproject.toml",
        '''\
        [project]
        name = "memorylayer-client"
        version = "0.0.0"
        ''',
    )
    write_file(
        root / "memorylayer-sdk-python/src/memorylayer/__init__.py",
        '__version__ = "0.0.0"\n',
    )

    # memorylayer-sdk-langchain-python (consumer of memorylayer-client + pydantic)
    write_file(
        root / "memorylayer-sdk-langchain-python/pyproject.toml",
        '''\
        [project]
        name = "memorylayer-sdk-langchain-python"
        version = "0.0.0"
        dependencies = [
            "memorylayer-client==0.0.0",
            "pydantic>=2.0",
        ]
        ''',
    )
    write_file(
        root / "memorylayer-sdk-langchain-python/src/memorylayer_langchain/__init__.py",
        '__version__ = "0.0.0"\n',
    )

    # memorylayer-cc-plugin (TS + plugin manifest)
    write_json(
        root / "memorylayer-cc-plugin/package.json",
        {
            "name": "@scitrera/memorylayer-cc-plugin",
            "version": "0.0.0",
            "dependencies": {
                "@scitrera/memorylayer-mcp-server": "0.0.0",
                "@modelcontextprotocol/sdk": "^1.0.0",
            },
        },
    )
    write_json(
        root / "memorylayer-cc-plugin/.claude-plugin/plugin.json",
        {"name": "memorylayer", "version": "0.0.0"},
    )

    # memorylayer-mcp-typescript (internal source-of-truth for @scitrera/memorylayer-mcp-server)
    write_json(
        root / "memorylayer-mcp-typescript/package.json",
        {
            "name": "@scitrera/memorylayer-mcp-server",
            "version": "0.0.0",
        },
    )

    write_file(
        root / "versions.yaml",
        '''\
        memorylayer-core-python: 0.1.22
        memorylayer-sdk-python: 0.1.22
        memorylayer-cc-plugin: 0.1.22
        memorylayer-sdk-langchain-python: 0.1.22
        memorylayer-mcp-typescript: 0.1.22

        preferred_versions:
          python:
            "pydantic": "2.13.4"
            "fastapi": "0.136.1"
          typescript:
            "@modelcontextprotocol/sdk": "^1.26.0"

        project_rules:
          memorylayer-core-python:
            - { type: pyproject, path: memorylayer-core-python/pyproject.toml }
            - { type: init_py,   path: memorylayer-core-python/src/memorylayer_server/__init__.py }
          memorylayer-sdk-python:
            - { type: pyproject, path: memorylayer-sdk-python/pyproject.toml }
            - { type: init_py,   path: memorylayer-sdk-python/src/memorylayer/__init__.py }
          memorylayer-sdk-langchain-python:
            - { type: pyproject, path: memorylayer-sdk-langchain-python/pyproject.toml }
            - { type: init_py,   path: memorylayer-sdk-langchain-python/src/memorylayer_langchain/__init__.py }
          memorylayer-cc-plugin:
            - { type: package,     path: memorylayer-cc-plugin/package.json }
            - { type: plugin,      path: memorylayer-cc-plugin/.claude-plugin/plugin.json }
            - { type: marketplace, path: .claude-plugin/marketplace.json, args: [memorylayer-cc-plugin] }
          memorylayer-mcp-typescript:
            - { type: package, path: memorylayer-mcp-typescript/package.json }

        dependency_mappings:
          python:
            packages:
              "memorylayer-sdk-python": "memorylayer-client"
            dependencies:
              memorylayer-sdk-langchain-python:
                - "memorylayer-sdk-python"
          typescript:
            packages:
              "memorylayer-mcp-typescript": "@scitrera/memorylayer-mcp-server"
            dependencies:
              memorylayer-cc-plugin:
                - "memorylayer-mcp-typescript"
        ''',
    )

    return root
