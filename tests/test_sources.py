"""Tests for source readers."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from scitrera_repo_tools.version_sync.sources import (
    package_lock_json,
    pipfile_lock,
    pnpm_lock_yaml,
    poetry_lock,
    requirements_txt,
    uv_lock,
)


def test_uv_lock_reader(tmp_path: Path) -> None:
    path = tmp_path / "uv.lock"
    path.write_text(
        dedent(
            '''\
            version = 1

            [[package]]
            name = "pydantic"
            version = "2.13.4"

            [[package]]
            name = "fastapi"
            version = "0.136.1"
            '''
        ),
        encoding="utf-8",
    )
    result = uv_lock.read(path)
    assert result == {"pydantic": "2.13.4", "fastapi": "0.136.1"}


def test_poetry_lock_reader(tmp_path: Path) -> None:
    path = tmp_path / "poetry.lock"
    path.write_text(
        dedent(
            '''\
            [[package]]
            name = "requests"
            version = "2.31.0"
            description = ""

            [metadata]
            lock-version = "2.0"
            '''
        ),
        encoding="utf-8",
    )
    result = poetry_lock.read(path)
    assert result == {"requests": "2.31.0"}


def test_requirements_txt_reader(tmp_path: Path) -> None:
    path = tmp_path / "requirements.txt"
    path.write_text(
        dedent(
            '''\
            # comment
            pydantic==2.13.4
            fastapi==0.136.1 ; python_version>='3.9'
            click==8.3.3
            no-version-here
            -e .
            '''
        ),
        encoding="utf-8",
    )
    result = requirements_txt.read(path)
    assert result == {
        "pydantic": "2.13.4",
        "fastapi": "0.136.1",
        "click": "8.3.3",
    }


def test_pipfile_lock_reader(tmp_path: Path) -> None:
    path = tmp_path / "Pipfile.lock"
    path.write_text(
        json.dumps(
            {
                "_meta": {"hash": {}},
                "default": {
                    "pydantic": {"version": "==2.13.4"},
                    "fastapi": {"version": "==0.136.1"},
                },
                "develop": {
                    "pytest": {"version": "==7.4.0"},
                },
            }
        ),
        encoding="utf-8",
    )
    result = pipfile_lock.read(path)
    assert result == {"pydantic": "2.13.4", "fastapi": "0.136.1", "pytest": "7.4.0"}


def test_package_lock_json_v3(tmp_path: Path) -> None:
    path = tmp_path / "package-lock.json"
    path.write_text(
        json.dumps(
            {
                "name": "x",
                "lockfileVersion": 3,
                "packages": {
                    "": {"version": "0.1.0"},
                    "node_modules/lodash": {"version": "4.17.21"},
                    "node_modules/@scope/pkg": {"version": "1.2.3"},
                },
            }
        ),
        encoding="utf-8",
    )
    result = package_lock_json.read(path)
    assert result["lodash"] == "4.17.21"
    assert result["@scope/pkg"] == "1.2.3"


def test_package_lock_json_v1(tmp_path: Path) -> None:
    path = tmp_path / "package-lock.json"
    path.write_text(
        json.dumps(
            {
                "name": "x",
                "lockfileVersion": 1,
                "dependencies": {
                    "lodash": {"version": "4.17.21"},
                    "@scope/pkg": {"version": "1.2.3"},
                },
            }
        ),
        encoding="utf-8",
    )
    result = package_lock_json.read(path)
    assert result["lodash"] == "4.17.21"
    assert result["@scope/pkg"] == "1.2.3"


def test_pnpm_lock_yaml(tmp_path: Path) -> None:
    path = tmp_path / "pnpm-lock.yaml"
    path.write_text(
        dedent(
            '''\
            lockfileVersion: '6.0'

            packages:

              /lodash@4.17.21:
                resolution: {}

              /@modelcontextprotocol/sdk@1.26.0:
                resolution: {}
            '''
        ),
        encoding="utf-8",
    )
    result = pnpm_lock_yaml.read(path)
    assert result["lodash"] == "4.17.21"
    assert result["@modelcontextprotocol/sdk"] == "1.26.0"
