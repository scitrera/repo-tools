"""Unknown-key rejection for the `ci:` block and its sub-blocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.version_sync.config import ConfigError, load_config


def _load(tmp_path: Path, write_file, ci_body: str):
    write_file(tmp_path / "versions.yaml", f"my-pkg: 0.1.0\n\nci:\n{ci_body}")
    return load_config(tmp_path / "versions.yaml")


@pytest.mark.parametrize("ci_body,where,bad", [
    ("  test_branchs: [main]\n", "ci", "test_branchs"),
    ("  repo_tools_srce: x\n", "ci", "repo_tools_srce"),
    ("  only_workflow: [proto-check]\n", "ci", "only_workflow"),
    ("  python:\n    test_verisons: ['3.12']\n", "ci.python", "test_verisons"),
    ("  python:\n    verify_tag: my-pkg\n", "ci.python", "verify_tag"),
    ("  npm:\n    node_verison: '24'\n", "ci.npm", "node_verison"),
    ("  go:\n    golangci_ver: v2.0.0\n", "ci.go", "golangci_ver"),
    ("  docker:\n    platforms: [linux/amd64]\n", "ci.docker", "platforms"),
])
def test_unknown_keys_rejected(tmp_path, write_file, ci_body, where, bad):
    with pytest.raises(ConfigError) as exc:
        _load(tmp_path, write_file, ci_body)
    msg = str(exc.value)
    assert msg.startswith(f"{where}: unknown key(s)")
    assert bad in msg
    # The error must name the valid options, not just complain.
    assert "expected one of" in msg


def test_every_documented_key_is_accepted(tmp_path, write_file):
    """Guard against the rejection list drifting behind the dataclasses."""
    cfg = _load(tmp_path, write_file, """\
  test_branches: [main, develop]
  bootstrap_method: uvx
  repo_tools_source: "scitrera-repo-tools==1.2.3"
  skip_workflows: [build-docker]
  only_workflows: [version-check]
  github_release: true
  python:
    test_versions: ["3.12"]
    lint: ruff
    install: pip install -e .
    pypi_environment: pypi
    publish_requires_tests: false
    verify_tag_version: my-pkg
  npm:
    node_version: "24"
    lint: eslint
    npm_environment: npm
    use_provenance: true
    use_oidc: true
  go:
    go_version: "1.25"
    lint: none
    golangci_version: v2.11.4
    enable_govulncheck: false
    test_args: -count=1
  docker:
    default_platforms: [linux/amd64]
    platform_runners: {linux/arm64: ubuntu-24.04-arm}
    build_on_pr: true
    enable_workflow_dispatch_version: false
    test_prereqs: [go]
""")
    assert cfg.ci.bootstrap_method == "uvx"
    assert cfg.ci.only_workflows == ("version-check",)
    assert cfg.ci.github_release is True
    assert cfg.ci.npm.use_oidc is True
    assert cfg.ci.go.lint == "none"
    assert cfg.ci.docker.build_on_pr is True


@pytest.mark.parametrize("ci_body,where,key", [
    ('  github_release: "no"\n', "ci", "github_release"),
    ('  python:\n    publish_requires_tests: "yes"\n', "ci.python", "publish_requires_tests"),
    ('  npm:\n    use_provenance: 1\n', "ci.npm", "use_provenance"),
    ('  npm:\n    use_oidc: "true"\n', "ci.npm", "use_oidc"),
    ('  go:\n    enable_govulncheck: "off"\n', "ci.go", "enable_govulncheck"),
    ('  go:\n    coverage: "no"\n', "ci.go", "coverage"),
    ('  docker:\n    build_on_pr: "false"\n', "ci.docker", "build_on_pr"),
    ('  docker:\n    enable_workflow_dispatch_version: 0\n',
     "ci.docker", "enable_workflow_dispatch_version"),
])
def test_boolean_flags_reject_non_booleans(tmp_path, write_file, ci_body, where, key):
    """`bool("no")` is True — a truthy coercion silently inverts the author's intent."""
    with pytest.raises(ConfigError) as exc:
        _load(tmp_path, write_file, ci_body)
    assert f"{where}.{key}: expected boolean" in str(exc.value)


def test_real_booleans_still_accepted(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, "  github_release: false\n  go:\n    coverage: true\n")
    assert cfg.ci.github_release is False
    assert cfg.ci.go.coverage is True


def test_github_release_moved_off_ci_python(tmp_path, write_file):
    """It moved to `ci:` level; the old spot must fail rather than be ignored.

    A silently-ignored `ci.python.github_release` would drop the GitHub Release
    from a tag push with no signal at all, which is worse than a hard error at
    parse time.
    """
    with pytest.raises(ConfigError) as exc:
        _load(tmp_path, write_file, "  python:\n    github_release: true\n")
    assert "ci.python: unknown key(s) ['github_release']" in str(exc.value)


def test_absent_and_empty_ci_still_fine(tmp_path, write_file):
    write_file(tmp_path / "versions.yaml", "my-pkg: 0.1.0\n")
    assert load_config(tmp_path / "versions.yaml").ci.test_branches == ("main", "develop")
    cfg = _load(tmp_path, write_file, "  {}\n")
    assert cfg.ci.bootstrap_method == "uvx"
