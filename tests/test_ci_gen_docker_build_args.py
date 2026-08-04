"""Tests for docker.images.<key>.build_args and preferred_versions substitution.

Two behaviours matter beyond "it emits the arg":

  * declared args MERGE with the BASE_IMAGE cascade rather than replacing it, so an
    image can inherit from a parent and still pin its own arguments
  * a `${preferred_versions:...}` reference resolves at PARSE time, so a bad
    reference is a config error naming the file rather than an empty build-arg
    that builds green and produces a subtly wrong image
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_build_docker
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

BASE = """\
app: 1.2.3

preferred_versions:
  python:
    scitrera-aether-client: "0.2.2"
    unpinned:
  container:
    ghcr.io/scitrera/aether: "0.4.1"

docker:
  ghcr: acme
  dockerhub: acme
  images:
    parent:
      context: .
      dockerfile: Dockerfile
    app:
      context: .
      dockerfile: Dockerfile
{app_extra}"""


def _load(tmp_path: Path, write_file, app_extra: str):
    write_file(tmp_path / "versions.yaml", BASE.format(app_extra=app_extra))
    return load_config(tmp_path / "versions.yaml")


def _render(tmp_path: Path, write_file, app_extra: str) -> dict:
    cfg = _load(tmp_path, write_file, app_extra)
    return yaml.safe_load(build_build_docker(cfg, cfg.ci))


def _build_args(doc: dict, job_substr: str) -> dict:
    """Parse the `build-args:` block of the first matching build job."""
    for name, job in doc["jobs"].items():
        if job_substr not in name:
            continue
        for step in job.get("steps", []):
            raw = (step.get("with") or {}).get("build-args")
            if raw:
                out = {}
                for line in raw.strip().splitlines():
                    key, _, value = line.partition("=")
                    out[key.strip()] = value
                return out
    return {}


class TestBuildArgsEmission:
    def test_declared_args_are_emitted(self, tmp_path, write_file):
        doc = _render(
            tmp_path,
            write_file,
            '      build_args:\n        FOO: "bar"\n        EMPTY: ""\n',
        )
        args = _build_args(doc, "app")
        assert args["FOO"] == "bar"
        assert args["EMPTY"] == "", "an explicitly empty arg must still be passed"

    def test_no_args_and_no_parent_emits_no_block(self, tmp_path, write_file):
        doc = _render(tmp_path, write_file, "")
        assert _build_args(doc, "app") == {}

    def test_declared_args_merge_with_base_image_cascade(self, tmp_path, write_file):
        """The cascade and custom args are not alternatives."""
        doc = _render(
            tmp_path,
            write_file,
            '      needs: parent\n      build_args:\n        FOO: "bar"\n',
        )
        args = _build_args(doc, "app")
        assert "BASE_IMAGE" in args, "parent cascade must survive"
        assert args["FOO"] == "bar", "declared arg must survive"

    def test_custom_base_image_arg_name_still_honored(self, tmp_path, write_file):
        doc = _render(
            tmp_path,
            write_file,
            '      needs: parent\n      base_image_arg: PARENT_IMG\n'
            '      build_args:\n        FOO: "bar"\n',
        )
        args = _build_args(doc, "app")
        assert "PARENT_IMG" in args
        assert args["FOO"] == "bar"

    def test_emission_order_is_stable(self, tmp_path, write_file):
        """Reordering the config must not show up as CI drift."""
        one = _render(
            tmp_path, write_file, '      build_args:\n        B: "2"\n        A: "1"\n'
        )
        two = _render(
            tmp_path, write_file, '      build_args:\n        A: "1"\n        B: "2"\n'
        )
        assert list(_build_args(one, "app")) == list(_build_args(two, "app"))


class TestPreferredVersionsSubstitution:
    def test_resolves_from_python_bucket(self, tmp_path, write_file):
        doc = _render(
            tmp_path,
            write_file,
            "      build_args:\n"
            '        CLIENT: "${preferred_versions:python:scitrera-aether-client}"\n',
        )
        assert _build_args(doc, "app")["CLIENT"] == "0.2.2"

    def test_resolves_from_an_arbitrary_bucket(self, tmp_path, write_file):
        """A container image tag is not a python or npm package."""
        doc = _render(
            tmp_path,
            write_file,
            "      build_args:\n"
            '        AETHER: "${preferred_versions:container:ghcr.io/scitrera/aether}"\n',
        )
        assert _build_args(doc, "app")["AETHER"] == "0.4.1"

    def test_substitution_is_verbatim_and_embeddable(self, tmp_path, write_file):
        """Values are pasted as declared — no spec/bare-version conversion."""
        doc = _render(
            tmp_path,
            write_file,
            "      build_args:\n"
            '        TAG: "v${preferred_versions:container:ghcr.io/scitrera/aether}-gpu"\n',
        )
        assert _build_args(doc, "app")["TAG"] == "v0.4.1-gpu"

    def test_unknown_language_is_a_config_error(self, tmp_path, write_file):
        with pytest.raises(ConfigError, match="no preferred_versions.rust block"):
            _load(
                tmp_path,
                write_file,
                '      build_args:\n        X: "${preferred_versions:rust:foo}"\n',
            )

    def test_unknown_package_is_a_config_error(self, tmp_path, write_file):
        with pytest.raises(ConfigError, match="not declared in preferred_versions"):
            _load(
                tmp_path,
                write_file,
                '      build_args:\n        X: "${preferred_versions:python:nope}"\n',
            )

    def test_empty_declared_value_is_a_config_error(self, tmp_path, write_file):
        """A null pin cannot be substituted; silently emitting '' would be worse."""
        with pytest.raises(ConfigError, match="is empty"):
            _load(
                tmp_path,
                write_file,
                '      build_args:\n        X: "${preferred_versions:python:unpinned}"\n',
            )


class TestBuildArgsValidation:
    def test_null_arg_value_is_rejected(self, tmp_path, write_file):
        with pytest.raises(ConfigError, match="null is not a value"):
            _load(tmp_path, write_file, "      build_args:\n        X:\n")

    def test_non_mapping_build_args_is_rejected(self, tmp_path, write_file):
        with pytest.raises(ConfigError):
            _load(tmp_path, write_file, "      build_args:\n        - X=1\n")

    def test_unknown_image_key_is_rejected(self, tmp_path, write_file):
        """Image descriptors previously ignored unknown keys, so typos were silent."""
        with pytest.raises(ConfigError, match="unknown key"):
            _load(tmp_path, write_file, "      buld_args:\n        X: \"1\"\n")
