"""Tests for source detect_reader."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from scitrera_repo_tools.version_sync.sources.detect import detect_reader


def test_detect_by_filename(tmp_path: Path) -> None:
    for name, expected in [
        ("uv.lock", "uv_lock"),
        ("poetry.lock", "poetry_lock"),
        ("Pipfile.lock", "pipfile_lock"),
        ("package-lock.json", "package_lock_json"),
        ("pnpm-lock.yaml", "pnpm_lock_yaml"),
        ("pnpm-lock.yml", "pnpm_lock_yaml"),
    ]:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        assert detect_reader(p) == expected, name


def test_detect_requirements_pattern(tmp_path: Path) -> None:
    p = tmp_path / "requirements-dev.txt"
    p.write_text("pydantic==2.0\n", encoding="utf-8")
    assert detect_reader(p) == "requirements_txt"


def test_detect_pipfile_by_content(tmp_path: Path) -> None:
    p = tmp_path / "weirdname.json"
    p.write_text(json.dumps({"_meta": {"hash": {}}, "default": {}}), encoding="utf-8")
    assert detect_reader(p) == "pipfile_lock"


def test_detect_package_lock_by_content(tmp_path: Path) -> None:
    p = tmp_path / "weirdname.json"
    p.write_text(json.dumps({"lockfileVersion": 3, "packages": {}}), encoding="utf-8")
    assert detect_reader(p) == "package_lock_json"


def test_detect_poetry_by_content(tmp_path: Path) -> None:
    p = tmp_path / "weirdname.lock"
    p.write_text(
        dedent(
            '''\
            [[package]]
            name = "x"

            [metadata]
            lock-version = "2.0"
            '''
        ),
        encoding="utf-8",
    )
    assert detect_reader(p) == "poetry_lock"


def test_detect_uv_by_content(tmp_path: Path) -> None:
    p = tmp_path / "weirdname.lock"
    p.write_text("[[package]]\nname = 'x'\n", encoding="utf-8")
    assert detect_reader(p) == "uv_lock"


def test_detect_pnpm_by_content(tmp_path: Path) -> None:
    p = tmp_path / "weirdname.yaml"
    p.write_text("lockfileVersion: '6.0'\npackages:\n", encoding="utf-8")
    assert detect_reader(p) == "pnpm_lock_yaml"


def test_detect_requirements_by_content(tmp_path: Path) -> None:
    p = tmp_path / "frozen.deps"
    p.write_text("pydantic==2.0.0\nfastapi==0.100.0\n", encoding="utf-8")
    assert detect_reader(p) == "requirements_txt"
