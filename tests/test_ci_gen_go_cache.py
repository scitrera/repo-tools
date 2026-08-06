"""setup-go cache inputs: a missing go.sum is either fine or fatal, never ignored."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.go_cache import (
    module_needs_checksums,
    parse_gomod_deps,
)
from scitrera_repo_tools.ci_gen_gha.templates import build_test_go
from scitrera_repo_tools.version_sync.config import load_config

VERSIONS = """\
spec: 1.0.0
project_rules:
  spec:
    - { type: gomod, path: go/go.mod }
ci:
  go:
    lint: none
    enable_govulncheck: false
"""


def _build(tmp_path: Path, gomod: str, gosum: str | None) -> dict:
    (tmp_path / "go").mkdir(exist_ok=True)
    (tmp_path / "go" / "go.mod").write_text(gomod, encoding="utf-8")
    if gosum is not None:
        (tmp_path / "go" / "go.sum").write_text(gosum, encoding="utf-8")
    (tmp_path / "versions.yaml").write_text(VERSIONS, encoding="utf-8")
    config = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_go(config, config.ci))


def _setup_go_with(doc: dict) -> dict:
    step = next(s for s in doc["jobs"]["test-spec"]["steps"] if "setup-go" in str(s.get("uses")))
    return step["with"]


# --- parsing ---------------------------------------------------------------

def test_parses_block_and_single_line_requires() -> None:
    requires, replaced = parse_gomod_deps(
        "module m\n\n"
        "go 1.25\n\n"
        "require example.com/single v1.0.0\n\n"
        "require (\n"
        "\texample.com/a v1.2.3\n"
        "\texample.com/b v0.1.0 // indirect\n"
        ")\n"
    )
    assert requires == {"example.com/single", "example.com/a", "example.com/b"}
    assert replaced == set()


def test_indirect_requirements_still_need_checksums(tmp_path: Path) -> None:
    """An indirect dependency is downloaded like any other, so it is verified."""
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module m\n\nrequire (\n\texample.com/b v0.1.0 // indirect\n)\n", encoding="utf-8"
    )
    assert module_needs_checksums(gomod) is True


def test_locally_replaced_requirement_needs_no_checksum(tmp_path: Path) -> None:
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module m\n\n"
        "require example.com/sibling v1.0.0\n\n"
        "replace example.com/sibling => ../sibling\n",
        encoding="utf-8",
    )
    assert module_needs_checksums(gomod) is False


def test_replacement_by_another_module_still_needs_checksums(tmp_path: Path) -> None:
    """A module-path replacement is still downloaded; only a directory is not."""
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module m\n\n"
        "require example.com/old v1.0.0\n\n"
        "replace example.com/old v1.0.0 => example.com/fork v1.0.1\n",
        encoding="utf-8",
    )
    assert module_needs_checksums(gomod) is True


def test_partially_replaced_still_needs_checksums(tmp_path: Path) -> None:
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module m\n\n"
        "require (\n"
        "\texample.com/sibling v1.0.0\n"
        "\texample.com/remote v2.0.0\n"
        ")\n\n"
        "replace example.com/sibling => ./sibling\n",
        encoding="utf-8",
    )
    assert module_needs_checksums(gomod) is True


def test_comments_do_not_create_phantom_requirements(tmp_path: Path) -> None:
    gomod = tmp_path / "go.mod"
    gomod.write_text(
        "module m\n\n// require example.com/commented v1.0.0\n", encoding="utf-8"
    )
    assert module_needs_checksums(gomod) is False


# --- rendering -------------------------------------------------------------

def test_go_sum_present_keys_the_cache_on_it(tmp_path: Path) -> None:
    doc = _build(
        tmp_path,
        "module m\n\nrequire example.com/a v1.0.0\n",
        "example.com/a v1.0.0 h1:x=\n",
    )
    assert _setup_go_with(doc)["cache-dependency-path"] == "go/go.sum"


def test_dependency_free_module_disables_the_cache(tmp_path: Path) -> None:
    """setup-go fails on an unresolvable cache path, so it must not be pointed at one."""
    doc = _build(tmp_path, "module m\n\ngo 1.25\n", None)
    with_block = _setup_go_with(doc)
    assert with_block["cache"] is False
    assert "cache-dependency-path" not in with_block


def test_missing_go_sum_with_real_dependencies_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="go.sum is missing"):
        _build(tmp_path, "module m\n\nrequire example.com/a v1.0.0\n", None)


def test_every_go_job_agrees_on_the_cache_inputs(tmp_path: Path) -> None:
    """Lint and govulncheck run the same setup-go step as the test job."""
    (tmp_path / "go").mkdir()
    (tmp_path / "go" / "go.mod").write_text("module m\n\ngo 1.25\n", encoding="utf-8")
    (tmp_path / "versions.yaml").write_text(
        "spec: 1.0.0\n"
        "project_rules:\n"
        "  spec:\n"
        "    - { type: gomod, path: go/go.mod }\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_test_go(config, config.ci))

    assert set(doc["jobs"]) == {"test-spec", "lint-spec", "security-spec"}
    for job in doc["jobs"].values():
        step = next(s for s in job["steps"] if "setup-go" in str(s.get("uses")))
        assert step["with"]["cache"] is False
        assert "cache-dependency-path" not in step["with"]
