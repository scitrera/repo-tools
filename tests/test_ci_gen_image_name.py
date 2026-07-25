"""Tests for docker.images.<key>.image_name and ci.go.coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_build_docker, build_test_go
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

DOCKER = '''\
app: 1.2.3

project_rules:
  app:
    - {{ type: gomod_require, path: go.mod }}

docker:
  ghcr: acme
  dockerhub: acme
  images:
    base:
      context: .
      dockerfile: Dockerfile
    variant:
      context: .
      dockerfile: Dockerfile
      needs: base
      tag_style: dev
{image_name_line}
'''


def _docker(tmp_path: Path, write_file, image_name_line: str = "") -> dict:
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", DOCKER.format(image_name_line=image_name_line))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_build_docker(cfg, cfg.ci))


def _all_image_refs(doc: dict) -> set:
    """Every registry ref mentioned in any metadata-action `images:` input."""
    refs = set()
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            imgs = (step.get("with") or {}).get("images")
            if imgs:
                refs.update(line.strip() for line in imgs.splitlines() if line.strip())
    return refs


def test_default_image_name_is_the_descriptor_key(tmp_path, write_file):
    refs = _all_image_refs(_docker(tmp_path, write_file))
    assert "ghcr.io/acme/base" in refs
    assert "ghcr.io/acme/variant" in refs


def test_image_name_overrides_the_pushed_repository(tmp_path, write_file):
    """The whole point: two descriptors, one repository, distinguished by tag."""
    doc = _docker(tmp_path, write_file, "      image_name: base\n")
    refs = _all_image_refs(doc)
    assert "ghcr.io/acme/base" in refs
    assert "acme/base" in refs
    # The descriptor key must no longer leak into the pushed name.
    assert not any(r.endswith("/variant") for r in refs), refs


def test_job_ids_still_use_the_descriptor_key(tmp_path, write_file):
    """Job ids must stay keyed on the descriptor, or two variants would collide."""
    doc = _docker(tmp_path, write_file, "      image_name: base\n")
    assert "build-variant" in doc["jobs"]
    assert "build-base" in doc["jobs"]


def test_cascade_base_image_uses_the_overridden_parent_name(tmp_path, write_file):
    """A child's BASE_IMAGE must point at the parent's real repository."""
    doc = _docker(
        tmp_path, write_file,
        "      image_name: base\n",
    )
    build_args = None
    for step in doc["jobs"]["build-variant"]["steps"]:
        ba = (step.get("with") or {}).get("build-args")
        if ba:
            build_args = ba
    assert build_args is not None
    assert "BASE_IMAGE=ghcr.io/acme/base:" in build_args


def test_parent_override_flows_into_child_base_image(tmp_path, write_file):
    """Override the *parent*; the child's BASE_IMAGE must follow it."""
    body = DOCKER.format(image_name_line="").replace(
        "    base:\n      context: .\n      dockerfile: Dockerfile\n",
        "    base:\n      context: .\n      dockerfile: Dockerfile\n      image_name: renamed\n",
    )
    write_file(tmp_path / "go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", body)
    cfg = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_build_docker(cfg, cfg.ci))
    build_args = None
    for step in doc["jobs"]["build-variant"]["steps"]:
        ba = (step.get("with") or {}).get("build-args")
        if ba:
            build_args = ba
    assert "BASE_IMAGE=ghcr.io/acme/renamed:" in build_args


def test_empty_image_name_rejected(tmp_path, write_file):
    with pytest.raises(ConfigError, match="image_name"):
        _docker(tmp_path, write_file, '      image_name: ""\n')


# ── ci.go.coverage ────────────────────────────────────────────────────────────

GO = '''\
app: 1.2.3

go_toolchain:
  go: "1.25.12"

project_rules:
  app:
    - {{ type: gomod_require, path: server/go.mod }}

ci:
  go:
{go_body}
'''


def _go(tmp_path: Path, write_file, go_body: str) -> dict:
    write_file(tmp_path / "server/go.mod", "module example.com/app\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", GO.format(go_body=go_body))
    cfg = load_config(tmp_path / "versions.yaml")
    return yaml.safe_load(build_test_go(cfg, cfg.ci))


def _test_step(doc: dict) -> dict:
    steps = doc["jobs"]["test-app"]["steps"]
    return next(s for s in steps if s.get("name") == "go test")


def test_coverage_off_by_default(tmp_path, write_file):
    doc = _go(tmp_path, write_file, "    test_args: -race -count=1\n")
    assert "-coverprofile" not in _test_step(doc)["run"]
    names = [s.get("name") for s in doc["jobs"]["test-app"]["steps"]]
    assert "Upload coverage artifact" not in names


def test_coverage_appends_flags_and_uploads(tmp_path, write_file):
    """One switch must do both, so a profile can never be written yet uncollected."""
    doc = _go(tmp_path, write_file, "    test_args: -short -race -count=1\n    coverage: true\n")
    run = _test_step(doc)["run"]
    assert run == "go test -short -race -count=1 -coverprofile=coverage.out -covermode=atomic ./..."

    upload = next(
        s for s in doc["jobs"]["test-app"]["steps"] if s.get("name") == "Upload coverage artifact"
    )
    assert upload["with"]["path"] == "server/coverage.out"
    # Per-project artifact name: uploads collide otherwise in a multi-module repo.
    assert upload["with"]["name"] == "go-coverage-app"
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "warn"


def test_coverage_rejects_non_boolean(tmp_path, write_file):
    with pytest.raises(ConfigError, match="expected boolean|coverage"):
        _go(tmp_path, write_file, "    coverage: yes-please\n")
