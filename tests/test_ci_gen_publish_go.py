"""Tests for the generated publish-go workflow and Go module-tag reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_go, render_all
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

BODY = '''\
app: 1.2.3

go_toolchain:
  go: "1.25.12"

project_rules:
  api:
    - {{ type: gomod_require, path: api/go.mod }}
  sdkgo:
    - {{ type: gomod_require, path: sdk/go/go.mod }}

ci:
  go:
    module_tags: {mode}
'''


def _repo(tmp_path: Path, write_file, *, server_module: str | None = None) -> None:
    write_file(tmp_path / "api/go.mod", "module example.com/repo/api\n\ngo 1.25\n")
    write_file(tmp_path / "sdk/go/go.mod", "module example.com/repo/sdk/go\n\ngo 1.25\n")
    if server_module is not None:
        write_file(tmp_path / "server/go.mod", f"module {server_module}\n\ngo 1.25\n")


def _cfg(tmp_path: Path, write_file, mode: str = "verify", extra_rules: str = ""):
    write_file(tmp_path / "versions.yaml", BODY.format(mode=mode).replace(
        "  sdkgo:\n    - { type: gomod_require, path: sdk/go/go.mod }\n",
        "  sdkgo:\n    - { type: gomod_require, path: sdk/go/go.mod }\n" + extra_rules,
    ))
    return load_config(tmp_path / "versions.yaml")


def _doc(tmp_path, write_file, mode: str = "verify") -> dict:
    _repo(tmp_path, write_file)
    cfg = _cfg(tmp_path, write_file, mode)
    return yaml.safe_load(build_publish_go(cfg, cfg.ci))


def test_not_generated_by_default(tmp_path, write_file):
    """Opt-in: a new workflow must not appear unbidden in existing repos."""
    _repo(tmp_path, write_file)
    cfg = _cfg(tmp_path, write_file, "none")
    assert build_publish_go(cfg, cfg.ci) == ""
    assert render_all(cfg)["publish-go.yml"] == ""


def test_registered_in_render_all(tmp_path, write_file):
    _repo(tmp_path, write_file)
    cfg = _cfg(tmp_path, write_file, "verify")
    assert render_all(cfg)["publish-go.yml"] != ""


def test_triggers_on_the_root_tag_only(tmp_path, write_file):
    """The root tag is the single release signal; submodule tags must not fire it."""
    doc = _doc(tmp_path, write_file)
    trig = doc[True]
    assert trig["push"]["tags"] == ["v*.*.*"]
    assert "workflow_dispatch" in trig


def test_module_dirs_are_derived_from_gomod_rules(tmp_path, write_file):
    doc = _doc(tmp_path, write_file)
    step = doc["jobs"]["module-tags"]["steps"][-1]
    assert step["env"]["MODULE_DIRS"] == "api sdk/go"


def test_verify_mode_is_read_only(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, "verify")
    job = doc["jobs"]["module-tags"]
    assert job["permissions"] == {"contents": "read"}
    assert job["name"] == "Verify Go module tags"
    assert "git push" not in job["steps"][-1]["run"]
    assert "git tag" not in job["steps"][-1]["run"]


def test_push_mode_requests_write_and_pushes(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, "push")
    job = doc["jobs"]["module-tags"]
    assert job["permissions"] == {"contents": "write"}
    assert job["name"] == "Publish Go module tags"
    run = job["steps"][-1]["run"]
    assert "git tag" in run and "git push origin" in run


def test_full_history_is_fetched(tmp_path, write_file):
    """Tag comparison needs the tags and the commits they point at."""
    doc = _doc(tmp_path, write_file)
    checkout = doc["jobs"]["module-tags"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["fetch-tags"] is True


def test_gates_on_tests_via_workflow_call(tmp_path, write_file):
    """Reuse the generated test workflow rather than duplicating its matrix."""
    doc = _doc(tmp_path, write_file)
    assert doc["jobs"]["tests"]["uses"] == "./.github/workflows/test-go.yml"
    assert doc["jobs"]["module-tags"]["needs"] == ["tests"]


def test_inlines_tests_when_test_go_is_not_managed(tmp_path, write_file):
    """A `uses:` pointing at an unmanaged workflow would be a dangling ref."""
    _repo(tmp_path, write_file)
    body = BODY.format(mode="verify").replace(
        "ci:\n", "ci:\n  only_workflows: [publish-go]\n"
    )
    write_file(tmp_path / "versions.yaml", body)
    cfg = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_publish_go(cfg, cfg.ci))
    assert "tests" not in doc["jobs"]
    assert "test-api" in doc["jobs"] and "test-sdkgo" in doc["jobs"]
    assert set(doc["jobs"]["module-tags"]["needs"]) == {"test-api", "test-sdkgo"}


def test_module_path_directory_mismatch_is_a_generation_error(tmp_path, write_file):
    """The phantom-module trap: go.mod claiming the repo-root path from a subdir.

    Go fetches a nested module by directory, so such a module is unreachable
    under either name — and the proxy will synthesize an empty root module that
    resolves but carries none of the real dependencies.
    """
    _repo(tmp_path, write_file, server_module="example.com/repo")
    cfg = _cfg(
        tmp_path, write_file, "verify",
        extra_rules="  server:\n    - { type: gomod_require, path: server/go.mod }\n",
    )
    with pytest.raises(ValueError) as exc:
        build_publish_go(cfg, cfg.ci)
    msg = str(exc.value)
    assert "server/go.mod declares module 'example.com/repo'" in msg
    assert "must end with '/server'" in msg
    assert "ci.go.module_tags: none" in msg


def test_correctly_pathed_nested_module_passes(tmp_path, write_file):
    _repo(tmp_path, write_file, server_module="example.com/repo/server")
    cfg = _cfg(
        tmp_path, write_file, "verify",
        extra_rules="  server:\n    - { type: gomod_require, path: server/go.mod }\n",
    )
    doc = yaml.safe_load(build_publish_go(cfg, cfg.ci))
    assert doc["jobs"]["module-tags"]["steps"][-1]["env"]["MODULE_DIRS"] == "api sdk/go server"


def test_no_nested_modules_generates_nothing(tmp_path, write_file):
    """A single root module is released by the root tag; nothing to reconcile."""
    write_file(tmp_path / "go.mod", "module example.com/repo\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", '''\
app: 1.2.3
project_rules:
  app:
    - { type: gomod_require, path: go.mod }
ci:
  go:
    module_tags: verify
''')
    cfg = load_config(tmp_path / "versions.yaml")
    assert build_publish_go(cfg, cfg.ci) == ""


def test_invalid_mode_rejected(tmp_path, write_file):
    _repo(tmp_path, write_file)
    with pytest.raises(ConfigError, match="module_tags"):
        _cfg(tmp_path, write_file, "yolo")


def test_deterministic(tmp_path, write_file):
    assert _doc(tmp_path, write_file) == _doc(tmp_path, write_file)
