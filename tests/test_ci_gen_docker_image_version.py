"""`${image_version}` in build_args: stamp the artifact with the tag's version."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_build_docker
from scitrera_repo_tools.version_sync.config import load_config

BASE = """\
gateway: 0.0.1
project_rules:
  gateway:
    - { type: gomod, path: go.mod }
docker:
  ghcr: acme
  images:
    gateway:
      context: .
      dockerfile: Dockerfile
"""


def _build(tmp_path: Path, image_block: str) -> dict:
    (tmp_path / "go.mod").write_text("module m\n\ngo 1.25\n", encoding="utf-8")
    (tmp_path / "versions.yaml").write_text(BASE + image_block, encoding="utf-8")
    config = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_build_docker(config, config.ci))


def _build_args(doc: dict) -> str:
    job = next(j for name, j in doc["jobs"].items() if name.startswith("build-"))
    step = next(s for s in job["steps"] if "build-push-action" in str(s.get("uses")))
    return step["with"]["build-args"]


def test_image_version_resolves_to_the_version_step(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "      version_from: gateway\n"
        "      build_args:\n"
        '        VERSION: "${image_version}"\n',
    )
    assert "VERSION=${{ steps.imgver.outputs.version }}" in _build_args(doc)


def test_image_version_can_be_embedded_in_a_larger_value(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "      version_from: gateway\n"
        "      build_args:\n"
        '        TAG: "v${image_version}-oss"\n',
    )
    assert "TAG=v${{ steps.imgver.outputs.version }}-oss" in _build_args(doc)


def test_image_version_without_version_from_is_an_error(tmp_path: Path) -> None:
    """Silently expanding to an empty build-arg would ship a blank version."""
    with pytest.raises(ValueError, match="version_from"):
        _build(
            tmp_path,
            "      build_args:\n        VERSION: \"${image_version}\"\n",
        )


def test_unrelated_build_args_are_untouched(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "      version_from: gateway\n"
        "      build_args:\n"
        '        FEATURE: "1"\n'
        '        EMPTY: ""\n',
    )
    args = _build_args(doc)
    assert "FEATURE=1" in args
    assert "EMPTY=" in args
    assert "steps.imgver" not in args
