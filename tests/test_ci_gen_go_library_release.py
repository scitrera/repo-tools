"""Tests for the GitHub release a single-module Go *library* cuts on its tag.

A Go library publishes nothing: no registry upload, no binaries, and — with one
root module — no per-module tags to reconcile either. Its release is the tag.
These cover the jobs generated for that case, and the two situations where the
release job must stay away: nobody asked for a release, or another language's
publish flow already owns it.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_go, render_all
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

LIB = '''\
mylib: 0.2.0

go_toolchain:
  go: "1.25.0"

project_rules:
  mylib:
    - {{ type: gomod, path: go.mod }}

ci:
  github_release: {release}
  go:
{go_block}'''


def _cfg(tmp_path: Path, write_file, *, release: str = "true", go_block: str = "    test_args: '-count=1'\n"):
    write_file(tmp_path / "go.mod", "module example.com/mylib\n\ngo 1.25\n")
    write_file(
        tmp_path / "versions.yaml", LIB.format(release=release, go_block=go_block)
    )
    return load_config(tmp_path / "versions.yaml")


def _doc(tmp_path, write_file, **kw) -> dict:
    cfg = _cfg(tmp_path, write_file, **kw)
    return yaml.safe_load(build_publish_go(cfg, cfg.ci))


def test_library_release_job_is_generated(tmp_path, write_file):
    doc = _doc(tmp_path, write_file)
    job = doc["jobs"]["github-release"]
    assert job["permissions"]["contents"] == "write"
    assert job["if"] == "github.ref_type == 'tag'"
    assert doc[True]["push"]["tags"] == ["v*.*.*"]


def test_release_attaches_no_files(tmp_path, write_file):
    """There is no artifact: `go get` resolves the tag from the proxy."""
    doc = _doc(tmp_path, write_file)
    step = doc["jobs"]["github-release"]["steps"][-1]
    assert step["uses"].startswith("softprops/action-gh-release@")
    assert step["with"] == {"generate_release_notes": True}


def test_release_waits_for_the_tests(tmp_path, write_file):
    """The tag may name a commit whose branch build passed against other deps."""
    doc = _doc(tmp_path, write_file)
    assert doc["jobs"]["github-release"]["needs"] == ["tests"]
    assert doc["jobs"]["tests"]["uses"] == "./.github/workflows/test-go.yml"


def test_registered_in_render_all(tmp_path, write_file):
    cfg = _cfg(tmp_path, write_file)
    assert render_all(cfg)["publish-go.yml"] != ""


def test_absent_without_github_release(tmp_path, write_file):
    cfg = _cfg(tmp_path, write_file, release="false")
    assert build_publish_go(cfg, cfg.ci) == ""


def test_verify_tag_job_gates_the_release(tmp_path, write_file):
    doc = _doc(
        tmp_path, write_file,
        go_block="    verify_tag_version: mylib\n",
    )
    assert "verify-tag" in doc["jobs"]
    assert doc["jobs"]["github-release"]["needs"] == ["tests", "verify-tag"]
    run = " ".join(
        s.get("run", "") for s in doc["jobs"]["verify-tag"]["steps"]
    )
    assert "sync-versions --print-version mylib" in run


def test_verify_tag_version_rejects_an_unknown_project(tmp_path, write_file):
    """A typo would otherwise disable the check while looking configured."""
    with pytest.raises(ConfigError, match="ci.go.verify_tag_version"):
        _cfg(tmp_path, write_file, go_block="    verify_tag_version: nope\n")


PY_AND_GO = '''\
mylib: 0.2.0
mypkg: 0.2.0

go_toolchain:
  go: "1.25.0"

project_rules:
  mylib:
    - { type: gomod, path: go.mod }
  mypkg:
    - { type: pyproject, path: py/pyproject.toml }

ci:
  github_release: true
'''


def test_python_publish_flow_keeps_ownership_of_the_release(tmp_path, write_file):
    """Two jobs creating one release is a race, not two releases.

    publish-python.yml already attaches its distributions to this tag, so the Go
    side must not add a second release job.
    """
    write_file(tmp_path / "go.mod", "module example.com/mylib\n\ngo 1.25\n")
    write_file(
        tmp_path / "py/pyproject.toml",
        '[project]\nname = "mypkg"\nversion = "0.2.0"\n',
    )
    write_file(tmp_path / "versions.yaml", PY_AND_GO)
    cfg = load_config(tmp_path / "versions.yaml")

    assert build_publish_go(cfg, cfg.ci) == ""
    assert "github-release" in yaml.safe_load(render_all(cfg)["publish-python.yml"])["jobs"]
