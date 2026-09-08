from dataclasses import replace
import os
import subprocess

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import render_all
from scitrera_repo_tools.ci_gen_gha.runner import run
from scitrera_repo_tools.version_sync.config import load_config, ConfigError


def config(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core/go.mod").write_text("module example.com/repo/core\n\ngo 1.26\n")
    (tmp_path / "client").mkdir()
    (tmp_path / "client/pyproject.toml").write_text('[project]\nname="client"\nversion="2.3.4"\n')
    body = {
        "core": "0.7.1", "client": "2.3.4",
        "project_rules": {"core": [{"type": "gomod", "path": "core/go.mod"}],
                          "client": [{"type": "pyproject", "path": "client/pyproject.toml"}]},
        "ci": {"release_mode": "independent", "github_release": True,
               "go": {"lint": "none", "enable_govulncheck": False},
               "python": {"lint": "none"},
               "docker": {"test_prereqs": ["go"]}},
        "docker": {"ghcr": "example", "images": {
            "core": {"context": ".", "dockerfile": "Dockerfile", "version_from": "core"}}},
    }
    path = tmp_path / "versions.yaml"
    path.write_text(yaml.safe_dump(body))
    return load_config(path)


def test_release_scopes_artifacts_and_validates_needs(tmp_path):
    rendered = render_all(config(tmp_path))
    assert not rendered["publish-go.yml"]
    assert not rendered["publish-python.yml"]
    assert not rendered["build-docker.yml"]
    core = yaml.safe_load(rendered["release-core.yml"])
    client = yaml.safe_load(rendered["release-client.yml"])
    assert core["on"] == {"push": {"tags": ["core/v*.*.*"]}}
    assert client["on"] == {"push": {"tags": ["client/v*.*.*"]}}
    assert "publish-client" not in core["jobs"]
    assert not any(k.startswith("build-") for k in client["jobs"])
    for doc in (core, client):
        jobs = doc["jobs"]
        for name, job in jobs.items():
            assert all(n in jobs for n in job.get("needs", []))
            if name != "verify-tag":
                assert "verify-tag" in job["needs"]
    assert "git push" not in rendered["release-core.yml"]
    assert "steps.ver." not in rendered["release-core.yml"]


@pytest.mark.parametrize("tag,expected", [("core/v0.7.1", 0), ("core/v0.7.2", 1), ("client/v0.7.1", 1), ("v0.7.1", 1)])
def test_tag_gate_executes(tmp_path, tag, expected):
    doc = yaml.safe_load(render_all(config(tmp_path))["release-core.yml"])
    script = doc["jobs"]["verify-tag"]["steps"][-1]["run"]
    # Fake only the version provider; execute the actual generated comparison.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uvx = bin_dir / "uvx"
    uvx.write_text("#!/bin/sh\nprintf '0.7.1\\n'\n")
    uvx.chmod(0o755)
    result = subprocess.run(["bash", "-c", script], env={**os.environ, "GITHUB_REF_NAME": tag,
                            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}, capture_output=True)
    assert result.returncode == expected


def test_independent_workflow_can_be_selected_and_checked(tmp_path):
    cfg = config(tmp_path)
    cfg = replace(cfg, ci=replace(cfg.ci, only_workflows=("release-core",)))
    assert run(cfg, workflows_dir=tmp_path / ".github/workflows", force=False, check_only=False) == 0
    assert list((tmp_path / ".github/workflows").glob("*.yml")) == [tmp_path / ".github/workflows/release-core.yml"]
    assert run(cfg, workflows_dir=tmp_path / ".github/workflows", force=False, check_only=True) == 0


def test_go_services_env_and_steps(tmp_path):
    cfg = config(tmp_path)
    raw = yaml.safe_load(cfg.yaml_path.read_text())
    raw["ci"]["go"].update({"services": {"pg": {"image": "postgres:16"}},
        "env": {"TEST_DATABASE_URL": "postgres://test"},
        "setup_steps": [{"name": "Before", "run": "true"}],
        "extra_steps": [{"name": "After", "run": "true"}]})
    cfg.yaml_path.write_text(yaml.safe_dump(raw))
    doc = yaml.safe_load(render_all(load_config(cfg.yaml_path))["test-go.yml"])
    job = doc["jobs"]["test-core"]
    assert job["env"]["TEST_DATABASE_URL"] == "postgres://test"
    assert job["services"]["pg"]["image"] == "postgres:16"
    names = [s.get("name") for s in job["steps"]]
    assert names.index("Before") < names.index("go test") < names.index("After")


def test_unknown_release_mode_is_rejected(tmp_path):
    cfg = config(tmp_path)
    cfg.yaml_path.write_text(cfg.yaml_path.read_text().replace("independent", "independant"))
    with pytest.raises(ConfigError, match="release_mode"):
        load_config(cfg.yaml_path)


def test_generated_workflow_drift_gate(tmp_path):
    cfg = config(tmp_path)
    cfg = replace(cfg, ci=replace(cfg.ci, check_generated_ci=True))
    rendered = render_all(cfg)["version-check.yml"]
    doc = yaml.safe_load(rendered)
    assert ".github/workflows/**" in doc[True]["pull_request"]["paths"]
    assert "generate-ci-gha --check" in rendered
