"""Rehearse generated publish builds without a registry or prebuilt siblings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_npm, build_test_npm
from scitrera_repo_tools.version_sync.config import ConfigError, load_config


def _repo(root: Path, *, npm=None, only=False, private=False):
    # Alphabetical order is deliberately different from build order.
    projects = {"z-sdk": "packages/sdk", "a-mid": "packages/mid", "leaf": "plugins/leaf"}
    dependencies = {"a-mid": ["z-sdk"], "leaf": ["a-mid"]}
    packages = {name: f"@fixture/{name}" for name in projects}
    for name, directory in projects.items():
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        deps = dependencies.get(name, [])
        manifest = {
            "name": packages[name], "version": "0.2.0", "main": "dist/index.js",
            "files": ["dist"], "scripts": {"build": "node build.js"},
            "dependencies": {
                packages[dep]: "file:" + os.path.relpath(root / projects[dep], path)
                for dep in deps
            },
        }
        if private and name == "z-sdk":
            manifest["private"] = True
        (path / "package.json").write_text(json.dumps(manifest))
        expression = " + ".join([f"require('{packages[dep]}')" for dep in deps] + ["1"])
        (path / "build.js").write_text(
            "const fs = require('node:fs');\n"
            f"const value = {expression};\n"
            "fs.mkdirSync('dist', {recursive: true});\n"
            "fs.writeFileSync('dist/index.js', `module.exports = ${value};`);\n"
        )
    body = {
        **{p: "0.2.0" for p in projects},
        "project_rules": {p: [{"type": "package", "path": f"{d}/package.json"}]
                          for p, d in projects.items()},
        "dependency_mappings": {"typescript": {"packages": packages, "dependencies": dependencies}},
        "ci": {"bootstrap_method": "pip", "npm": {"build": True, **(npm or {})}},
    }
    if only:
        body["ci"]["only_workflows"] = ["publish-npm"]
    (root / "versions.yaml").write_text(yaml.safe_dump(body, sort_keys=False))
    return load_config(root / "versions.yaml")


def _jobs(config):
    return yaml.safe_load(build_publish_npm(config, config.ci))["jobs"]


@pytest.mark.parametrize("npm", [
    {}, {"build": False}, {"publish_requires_tests": False},
    {"publish_projects": ["leaf"], "test_projects": ["z-sdk"]},
])
def test_publish_builds_full_dependency_closure(tmp_path, npm):
    jobs = _jobs(_repo(tmp_path, npm=npm, private=True))
    job = jobs["publish-leaf"]
    steps = job["steps"]
    builds = [s["working-directory"] for s in steps
              if s.get("name", "").startswith("Build in-repo")]
    assert builds == ["packages/sdk", "packages/mid"]
    assert not any("artifact" in s.get("uses", "") for s in steps)
    assert "publish-z-sdk" not in jobs
    for job in jobs.values():
        assert set(job.get("needs", [])) <= jobs.keys()


def test_inline_gate_keeps_test_selection_and_artifact_graph(tmp_path):
    config = _repo(tmp_path, npm={"test_projects": ["leaf"]}, only=True)
    standalone = yaml.safe_load(build_test_npm(config, config.ci))["jobs"]
    inline = _jobs(config)
    assert {k: v for k, v in inline.items() if k.startswith("test-")} == standalone
    assert set(inline["publish-leaf"]["needs"]) >= set(standalone)


def test_publish_setup_applies_before_each_install(tmp_path):
    config = _repo(tmp_path, npm={"setup_steps": [{"name": "Prepare", "run": "echo ready"}]})
    steps = _jobs(config)["publish-leaf"]["steps"]
    for directory in ["packages/sdk", "packages/mid", "plugins/leaf"]:
        setup = next(i for i, s in enumerate(steps)
                     if s.get("name") == "Prepare" and s["working-directory"] == directory)
        install = next(i for i, s in enumerate(steps)
                       if s.get("name", "").startswith("Install") and s.get("working-directory") == directory)
        assert setup < install


def _shell(command, cwd, env):
    return subprocess.run(["bash", "-euo", "pipefail", "-c", command], cwd=cwd,
                          env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not shutil.which("npm"), reason="npm is needed for the offline publish rehearsal")
@pytest.mark.parametrize("locked", [False, True])
def test_fresh_checkout_builds_and_packs_registry_pins(tmp_path, locked):
    config = _repo(tmp_path, npm={"publish_requires_tests": False, "publish_projects": ["leaf"]})
    env = {**os.environ, "npm_config_cache": str(tmp_path / "npm-cache"),
           "npm_config_offline": "true", "npm_config_audit": "false", "npm_config_fund": "false"}
    if locked:
        for directory in ["packages/sdk", "packages/mid", "plugins/leaf"]:
            result = _shell("npm install --package-lock-only --ignore-scripts", tmp_path / directory, env)
            assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.glob("**/dist"))
    assert not list(tmp_path.glob("**/node_modules"))

    for step in _jobs(config)["publish-leaf"]["steps"]:
        command = step.get("run", "")
        if not command or command.startswith("pip install"):
            continue
        cwd = tmp_path / step.get("working-directory", ".")
        if command.startswith("sync-versions"):
            from scitrera_repo_tools.version_sync.cli import main
            with pytest.raises(SystemExit) as exited:
                main(["--config", str(tmp_path / "versions.yaml"), *command.split()[1:]])
            assert exited.value.code == 0
            continue
        if step["name"] == "Publish to npm":
            command = "npm pack --json --ignore-scripts"
        result = _shell(command, cwd, env)
        assert result.returncode == 0, f"{step['name']}:\n{result.stdout}\n{result.stderr}"

    result = _shell("node -p \"require('./dist')\"", tmp_path / "plugins/leaf", env)
    assert result.stdout.strip() == "3", result.stderr
    archive = next((tmp_path / "plugins/leaf").glob("*.tgz"))
    with tarfile.open(archive) as tar:
        manifest = json.load(tar.extractfile("package/package.json"))
        assert manifest["dependencies"] == {"@fixture/a-mid": "0.2.0"}
        assert "package/dist/index.js" in tar.getnames()


@pytest.mark.skipif(not shutil.which("node"), reason="node is needed to execute the tag guard")
@pytest.mark.parametrize("ref,ok", [
    ("refs/tags/v0.2.0", True), ("refs/tags/v0.2.1", False),
    ("refs/heads/main", False), ("refs/heads/v0.2.0", False),
])
def test_matching_tag_guard_executes(tmp_path, ref, ok):
    config = _repo(tmp_path, npm={"require_matching_tag": True})
    step = next(s for s in _jobs(config)["publish-leaf"]["steps"]
                if s.get("name") == "Verify release tag matches package version")
    result = _shell(step["run"], tmp_path / "plugins/leaf", {**os.environ, "GITHUB_REF": ref})
    assert (result.returncode == 0) == ok, result.stdout + result.stderr


def test_matching_tag_opt_in_is_validated(tmp_path):
    with pytest.raises(ConfigError, match="require_matching_tag"):
        _repo(tmp_path, npm={"require_matching_tag": "yes"})
    config = _repo(tmp_path)
    assert "Verify release tag matches package version" not in build_publish_npm(config, config.ci)


def test_independent_tag_guard_uses_module_directory(tmp_path):
    from dataclasses import replace
    config = _repo(tmp_path, npm={"require_matching_tag": True})
    config = replace(config, ci=replace(config.ci, release_mode="independent"))
    assert 'expected="plugins/leaf/v$' in build_publish_npm(config, config.ci)
