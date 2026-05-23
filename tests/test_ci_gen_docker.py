"""Docker workflow generator + docker_order topology + config parsing."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_build_docker
from scitrera_repo_tools.ci_gen_gha.topology import docker_order
from scitrera_repo_tools.version_sync.config import ConfigError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "versions.yaml").write_text(body, encoding="utf-8")
    return tmp_path


@pytest.fixture
def aether_repo(tmp_path: Path) -> Path:
    """Mimics aether3's cascade (aether → aetherlite → aetherlite-dev)."""
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "go.mod").write_text("")
    (tmp_path / "server" / "go.sum").write_text("")
    _write(
        tmp_path,
        "gateway: 0.2.1\n"
        "go_toolchain:\n  go: '1.25.10'\n"
        "project_rules:\n"
        "  gateway:\n"
        "    - { type: gomod_require, path: server/go.mod, args: [ x ] }\n"
        "docker:\n"
        "  ghcr: scitrera\n"
        "  dockerhub: scitrera\n"
        "  images:\n"
        "    aether:\n"
        "      context: .\n"
        "      dockerfile: server/Dockerfile\n"
        "      version_from: gateway\n"
        "    aetherlite:\n"
        "      context: server\n"
        "      dockerfile: server/Dockerfile.aetherlite-dev\n"
        "      needs: aether\n"
        "      version_from: gateway\n"
        "    aetherlite-dev:\n"
        "      context: server\n"
        "      dockerfile: server/Dockerfile.aetherlite-dev\n"
        "      needs: aetherlite\n"
        "      tag_style: dev\n"
        "      version_from: gateway\n"
        "ci:\n"
        "  docker:\n"
        "    test_prereqs: [go]\n",
    )
    return tmp_path


def test_docker_order_cascade(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    order = docker_order(config)
    names = [n.name for n in order]
    assert names == ["aether", "aetherlite", "aetherlite-dev"]
    # Default platform_runners only includes linux/amd64 → strategy falls back to qemu.
    assert all(n.strategy == "qemu" for n in order)


def test_docker_order_native_when_runners_configured(aether_repo: Path) -> None:
    body = (aether_repo / "versions.yaml").read_text()
    body += "    platform_runners:\n      linux/arm64: ubuntu-24.04-arm\n"
    (aether_repo / "versions.yaml").write_text(body, encoding="utf-8")
    config = load_config(aether_repo / "versions.yaml")
    order = docker_order(config)
    assert all(n.strategy == "native" for n in order)


def test_docker_order_cycle_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docker:\n  ghcr: x\n  images:\n"
        "    a: { context: ., dockerfile: D, needs: b }\n"
        "    b: { context: ., dockerfile: D, needs: a }\n",
    )
    config = load_config(tmp_path / "versions.yaml")
    with pytest.raises(ValueError, match="Cyclic docker dependency"):
        docker_order(config)


def test_docker_parser_rejects_multi_parent(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="multi-parent cascades"):
        _write(
            tmp_path,
            "docker:\n  ghcr: x\n  images:\n"
            "    a: { context: ., dockerfile: D }\n"
            "    b: { context: ., dockerfile: D, needs: [a] }\n",
        )
        load_config(tmp_path / "versions.yaml")


def test_docker_parser_rejects_unknown_parent(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="parent image"):
        _write(
            tmp_path,
            "docker:\n  ghcr: x\n  images:\n"
            "    a: { context: ., dockerfile: D, needs: ghost }\n",
        )
        load_config(tmp_path / "versions.yaml")


def test_docker_parser_rejects_unknown_version_from(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a known project"):
        _write(
            tmp_path,
            "docker:\n  ghcr: x\n  images:\n"
            "    a: { context: ., dockerfile: D, version_from: missing }\n",
        )
        load_config(tmp_path / "versions.yaml")


def test_docker_workflow_yaml_valid(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    parsed = yaml.safe_load(text)  # raises if invalid
    assert "jobs" in parsed


def test_docker_workflow_has_both_registry_logins(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    assert "registry: ghcr.io" in text
    assert "DOCKERHUB_USERNAME" in text


def test_docker_workflow_only_ghcr(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docker:\n  ghcr: scitrera\n  images:\n"
        "    a: { context: ., dockerfile: D }\n",
    )
    config = load_config(tmp_path / "versions.yaml")
    text = build_build_docker(config, config.ci)
    assert "registry: ghcr.io" in text
    assert "DOCKERHUB_USERNAME" not in text


def test_docker_cascade_base_image_arg(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    # aetherlite cascades from aether via BASE_IMAGE pointing at GHCR.
    assert "BASE_IMAGE=ghcr.io/scitrera/aether:" in text
    assert "needs.build-aether.outputs.base-tag" in text  # qemu default
    # aetherlite-dev cascades from aetherlite.
    assert "BASE_IMAGE=ghcr.io/scitrera/aetherlite:" in text


def test_docker_native_cascade_uses_merge_job(aether_repo: Path) -> None:
    body = (aether_repo / "versions.yaml").read_text()
    body += "    platform_runners:\n      linux/arm64: ubuntu-24.04-arm\n"
    (aether_repo / "versions.yaml").write_text(body, encoding="utf-8")
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    # Native mode → children reference parent's merge job, not build job.
    assert "needs.merge-aether.outputs.base-tag" in text
    assert "merge-aetherlite-dev" in text


def test_docker_tag_style_dev_flavor_latest_false(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    # Standard images don't get the dev flavor; aetherlite-dev does.
    assert "latest=false" in text
    assert "type=raw,value=dev-latest" in text
    assert "type=sha,prefix=dev-" in text


def test_docker_version_from_step_emitted(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    assert "sync-versions --print-version gateway" in text
    assert "steps.imgver.outputs.version" in text


def test_docker_inlines_test_prereq(aether_repo: Path) -> None:
    config = load_config(aether_repo / "versions.yaml")
    text = build_build_docker(config, config.ci)
    parsed = yaml.safe_load(text)
    assert "test-gateway" in parsed["jobs"]
    # build-aether needs the test job.
    assert "test-gateway" in parsed["jobs"]["build-aether"]["needs"]


def test_docker_native_strategy_missing_runner_errors(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docker:\n  ghcr: x\n  images:\n"
        "    a:\n"
        "      context: .\n"
        "      dockerfile: D\n"
        "      platforms: [linux/amd64, linux/arm64]\n"
        "      build_strategy: native\n",
    )
    config = load_config(tmp_path / "versions.yaml")
    with pytest.raises(ValueError, match="no platform_runners entry"):
        docker_order(config)


def test_no_docker_block_yields_empty(tmp_path: Path) -> None:
    _write(tmp_path, "p: 0.1.0\nproject_rules:\n  p: []\n")
    config = load_config(tmp_path / "versions.yaml")
    assert build_build_docker(config, config.ci) == ""


def test_docker_without_registries_errors(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docker:\n  images:\n"
        "    a: { context: ., dockerfile: D }\n",
    )
    config = load_config(tmp_path / "versions.yaml")
    with pytest.raises(ValueError, match="at least one of"):
        build_build_docker(config, config.ci)
