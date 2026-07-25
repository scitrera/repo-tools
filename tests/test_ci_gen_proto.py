"""Tests for the generated proto-check workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_proto_check, render_all
from scitrera_repo_tools.version_sync.config import load_config

FULL = '''\
my-pkg: 0.1.0

go_toolchain:
  go: "1.25.12"

preferred_versions:
  go:
    "google.golang.org/protobuf": "1.36.11"

proto:
  dir: api/proto
  files: [thing.proto]
  toolchain:
    protoc: "33.5"
    protoc_gen_go_grpc: "v1.6.2"
    grpcio_tools: "1.81.1"
    proto_loader: "0.8.1"
  outputs:
    go:
      path: api/proto
    python:
      path: sdk/py/pkg/proto
    typescript:
      path: sdk/ts/src/proto
      package_dir: sdk/ts
'''


def _load(tmp_path: Path, write_file, body: str = FULL):
    write_file(tmp_path / "versions.yaml", body)
    return load_config(tmp_path / "versions.yaml")


def _render(tmp_path, write_file, body: str = FULL) -> str:
    cfg = _load(tmp_path, write_file, body)
    return build_proto_check(cfg, cfg.ci)


def _yaml(text: str) -> dict:
    return yaml.safe_load(text)


def test_no_proto_block_generates_nothing(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, "my-pkg: 0.1.0\n")
    assert build_proto_check(cfg, cfg.ci) == ""


def test_registered_in_render_all(tmp_path, write_file):
    cfg = _load(tmp_path, write_file)
    assert render_all(cfg)["proto-check.yml"] != ""


def test_output_is_valid_yaml_with_one_job_per_language(tmp_path, write_file):
    doc = _yaml(_render(tmp_path, write_file))
    assert sorted(doc["jobs"]) == [
        "proto-check-go", "proto-check-python", "proto-check-typescript",
    ]


def test_only_configured_languages_get_jobs(tmp_path, write_file):
    body = ("my-pkg: 0.1.0\nproto:\n  dir: api\n  files: [a.proto]\n"
            "  toolchain: {grpcio_tools: '1.81.1'}\n"
            "  outputs:\n    python: {path: out}\n")
    doc = _yaml(_render(tmp_path, write_file, body))
    assert list(doc["jobs"]) == ["proto-check-python"]


def test_trigger_paths_cover_inputs_and_every_output(tmp_path, write_file):
    doc = _yaml(_render(tmp_path, write_file))
    paths = doc[True]["pull_request"]["paths"]   # PyYAML parses bare `on:` as True
    assert set(paths) == {
        "versions.yaml",
        "api/proto/**",
        "sdk/py/pkg/proto/**",
        "sdk/ts/src/proto/**",
    }


def test_pins_are_interpolated_from_proto_toolchain(tmp_path, write_file):
    """Versions in the workflow must come from versions.yaml, not be hardcoded."""
    text = _render(tmp_path, write_file)
    assert "version: '33.5'" in text
    assert "protoc-gen-go@v1.36.11" in text          # derived from preferred_versions
    assert "protoc-gen-go-grpc@v1.6.2" in text
    assert "pip install grpcio-tools==1.81.1" in text


def test_go_version_comes_from_go_toolchain(tmp_path, write_file):
    assert "go-version: '1.25.12'" in _render(tmp_path, write_file)


def test_each_job_restricts_to_its_own_language(tmp_path, write_file):
    """The per-language split is what lets each job install only its toolchain."""
    doc = _yaml(_render(tmp_path, write_file))
    for lang in ("go", "python", "typescript"):
        run = doc["jobs"][f"proto-check-{lang}"]["steps"][-1]["run"]
        assert f"--lang {lang}" in run
        assert "--check" in run


def test_python_job_targets_the_interpreter_holding_grpcio_tools(tmp_path, write_file):
    """Under uvx, repo-tools runs in uv's env where grpc_tools is absent."""
    doc = _yaml(_render(tmp_path, write_file))
    run = doc["jobs"]["proto-check-python"]["steps"][-1]["run"]
    assert '--python "$(which python)"' in run


def test_typescript_job_runs_npm_ci_in_the_package_dir(tmp_path, write_file):
    doc = _yaml(_render(tmp_path, write_file))
    steps = doc["jobs"]["proto-check-typescript"]["steps"]
    npm = [s for s in steps if s.get("run") == "npm ci"]
    assert len(npm) == 1
    assert npm[0]["working-directory"] == "sdk/ts"


def test_typescript_package_dir_discovered_when_omitted(tmp_path, write_file, write_json):
    body = FULL.replace("      package_dir: sdk/ts\n", "")
    write_json(tmp_path / "sdk/ts/package.json", {"name": "ts"})
    (tmp_path / "sdk/ts/src/proto").mkdir(parents=True)
    doc = _yaml(_render(tmp_path, write_file, body))
    steps = doc["jobs"]["proto-check-typescript"]["steps"]
    npm = [s for s in steps if s.get("run") == "npm ci"]
    assert npm[0]["working-directory"] == "sdk/ts"


def test_grpc_false_skips_the_grpc_plugin(tmp_path, write_file):
    body = FULL.replace("    go:\n      path: api/proto",
                        "    go:\n      path: api/proto\n      grpc: false")
    text = _render(tmp_path, write_file, body)
    assert "protoc-gen-go@v1.36.11" in text
    assert "protoc-gen-go-grpc" not in text


def test_bootstrap_respects_pip_method(tmp_path, write_file):
    body = FULL.replace("my-pkg: 0.1.0\n",
                        "my-pkg: 0.1.0\n\nci:\n  bootstrap_method: pip\n")
    text = _render(tmp_path, write_file, body)
    assert "pip install scitrera-repo-tools" in text
    assert "uvx --from" not in text


def test_repo_tools_source_is_honored(tmp_path, write_file):
    body = FULL.replace(
        "my-pkg: 0.1.0\n",
        'my-pkg: 0.1.0\n\nci:\n  repo_tools_source: "scitrera-repo-tools==0.1.12"\n',
    )
    assert "uvx --from 'scitrera-repo-tools==0.1.12'" in _render(tmp_path, write_file, body)


def test_deterministic_output(tmp_path, write_file):
    assert _render(tmp_path, write_file) == _render(tmp_path, write_file)


@pytest.mark.parametrize("drop,expected", [
    ('    protoc: "33.5"\n', "proto.toolchain.protoc"),
    ('    protoc_gen_go_grpc: "v1.6.2"\n', "proto.toolchain.protoc_gen_go_grpc"),
    ('    grpcio_tools: "1.81.1"\n', "proto.toolchain.grpcio_tools"),
    ('    proto_loader: "0.8.1"\n', "proto.toolchain.proto_loader"),
])
def test_unpinned_tools_are_a_generation_error(tmp_path, write_file, drop, expected):
    """An unpinned compiler in CI is worse than no workflow — fail loudly."""
    with pytest.raises(ValueError) as exc:
        _render(tmp_path, write_file, FULL.replace(drop, ""))
    assert expected in str(exc.value)
    assert "skip_workflows" in str(exc.value)


def test_missing_protoc_gen_go_pin_reported_when_underivable(tmp_path, write_file):
    body = FULL.replace('  go:\n    "google.golang.org/protobuf": "1.36.11"\n', "  go: {}\n")
    with pytest.raises(ValueError, match="protoc_gen_go"):
        _render(tmp_path, write_file, body)


def test_skip_workflows_suppresses_generation(tmp_path, write_file):
    """The documented escape hatch must actually drop the entry."""
    from scitrera_repo_tools.ci_gen_gha.runner import run
    body = FULL.replace("my-pkg: 0.1.0\n",
                        "my-pkg: 0.1.0\n\nci:\n  skip_workflows: [proto-check]\n")
    cfg = _load(tmp_path, write_file, body)
    out = tmp_path / "wf"
    assert run(cfg, workflows_dir=out, force=False, check_only=False) == 0
    assert not (out / "proto-check.yml").exists()
