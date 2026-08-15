"""Tests for cross-compiled Go release binaries in the generated publish-go workflow."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path
from textwrap import indent

import pytest
import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_go, render_all
from scitrera_repo_tools.version_sync.config import ConfigError, load_config

HEAD = '''\
app: 1.2.3

go_toolchain:
  go: "1.25.12"

project_rules:
  app:
    - { type: gomod, path: go.mod }

ci:
  github_release: true
  go:
'''


def _cfg(tmp_path: Path, write_file, go_block: str, *, extra_ci: str = "", head: str = HEAD):
    write_file(tmp_path / "go.mod", "module example.com/repo\n\ngo 1.25\n")
    body = head + indent(go_block, "    ")
    if extra_ci:
        body = body.replace("ci:\n", "ci:\n" + indent(extra_ci, "  "))
    write_file(tmp_path / "versions.yaml", body)
    return load_config(tmp_path / "versions.yaml")


def _doc(tmp_path: Path, write_file, go_block: str, **kw) -> dict:
    cfg = _cfg(tmp_path, write_file, go_block, **kw)
    return yaml.safe_load(build_publish_go(cfg, cfg.ci))


ONE_BINARY = '''\
binaries:
  - name: app
    package: ./cmd/app
    platforms: [ linux/amd64, linux/arm64, windows/amd64, windows/arm64, darwin/arm64 ]
'''


def test_no_binaries_leaves_only_the_release(tmp_path, write_file):
    """A root-only module with no binaries has nothing to *build*, but still releases.

    HEAD sets `github_release: true`, which is the whole request for a library:
    cut the release for the tag. What must not appear is any build job.
    """
    cfg = _cfg(tmp_path, write_file, "test_args: '-count=1'\n")
    doc = yaml.safe_load(build_publish_go(cfg, cfg.ci))
    assert [j for j in doc["jobs"] if j.startswith("build-")] == []
    assert doc["jobs"]["github-release"]["permissions"]["contents"] == "write"


def test_no_binaries_and_no_release_generates_nothing(tmp_path, write_file):
    """Opt-in: without `github_release` a root-only library publishes nothing."""
    cfg = _cfg(
        tmp_path, write_file, "test_args: '-count=1'\n",
        head=HEAD.replace("  github_release: true\n", ""),
    )
    assert build_publish_go(cfg, cfg.ci) == ""


def test_binaries_alone_render_the_workflow(tmp_path, write_file):
    """Module tags are irrelevant for a single root module; the binaries are the release."""
    cfg = _cfg(tmp_path, write_file, ONE_BINARY)
    assert cfg.ci.go.module_tags == "none"
    assert render_all(cfg)["publish-go.yml"] != ""


def test_matrix_covers_every_declared_platform(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, ONE_BINARY)
    include = doc["jobs"]["build-app"]["strategy"]["matrix"]["include"]
    assert include == [
        {"goos": "linux", "goarch": "amd64"},
        {"goos": "linux", "goarch": "arm64"},
        {"goos": "windows", "goarch": "amd64"},
        {"goos": "windows", "goarch": "arm64"},
        {"goos": "darwin", "goarch": "arm64"},
    ]
    assert doc["jobs"]["build-app"]["strategy"]["fail-fast"] is False


def test_platforms_default_to_the_full_matrix(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, "binaries:\n  - name: app\n")
    include = doc["jobs"]["build-app"]["strategy"]["matrix"]["include"]
    assert {(e["goos"], e["goarch"]) for e in include} == {
        ("linux", "amd64"), ("linux", "arm64"),
        ("darwin", "amd64"), ("darwin", "arm64"),
        ("windows", "amd64"), ("windows", "arm64"),
    }


def test_binary_platforms_overrides_the_default(tmp_path, write_file):
    doc = _doc(
        tmp_path, write_file,
        "binary_platforms: [ linux/amd64 ]\nbinaries:\n  - name: app\n",
    )
    assert doc["jobs"]["build-app"]["strategy"]["matrix"]["include"] == [
        {"goos": "linux", "goarch": "amd64"}
    ]


def test_artifact_name_is_unique_per_matrix_leg(tmp_path, write_file):
    """A shared artifact name makes every leg but one vanish silently."""
    doc = _doc(tmp_path, write_file, ONE_BINARY)
    upload = doc["jobs"]["build-app"]["steps"][-1]
    assert upload["with"]["name"] == (
        "binaries-app-${{ matrix.goos }}-${{ matrix.goarch }}"
    )
    assert upload["with"]["if-no-files-found"] == "error"


def test_build_is_cgo_free_and_trimpath(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, ONE_BINARY)
    step = doc["jobs"]["build-app"]["steps"][-2]
    assert step["env"]["CGO_ENABLED"] == "0"
    assert step["env"]["GOOS"] == "${{ matrix.goos }}"
    assert "go build -trimpath" in step["run"]
    assert "./cmd/app" in step["run"]


def test_env_can_override_cgo(tmp_path, write_file):
    doc = _doc(
        tmp_path, write_file,
        'binaries:\n  - name: app\n    env:\n      CGO_ENABLED: "1"\n',
    )
    step = doc["jobs"]["build-app"]["steps"][-2]
    assert step["env"]["CGO_ENABLED"] == "1"


def test_ldflags_default_strips_and_expands_shell_vars(tmp_path, write_file):
    """`$VERSION`/`$COMMIT` must reach `go build` unexpanded by config parsing."""
    doc = _doc(
        tmp_path, write_file,
        "binaries:\n  - name: app\n    ldflags: -s -w -X main.commit=$COMMIT\n",
    )
    run = doc["jobs"]["build-app"]["steps"][-2]["run"]
    assert '-ldflags "-s -w -X main.commit=$COMMIT"' in run
    assert 'COMMIT="$GITHUB_SHA"' in run


def test_empty_ldflags_omits_the_flag(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, 'binaries:\n  - name: app\n    ldflags: ""\n')
    run = doc["jobs"]["build-app"]["steps"][-2]["run"]
    assert "-ldflags" not in run


def test_dispatch_run_still_names_its_assets(tmp_path, write_file):
    """workflow_dispatch has no tag; an empty version would produce `app__linux_amd64`."""
    run = _doc(tmp_path, write_file, ONE_BINARY)["jobs"]["build-app"]["steps"][-2]["run"]
    assert '0.0.0-dev.${GITHUB_SHA:0:7}' in run
    assert '${GITHUB_REF_NAME#v}' in run


def test_auto_archive_branches_on_goos(tmp_path, write_file):
    run = _doc(tmp_path, write_file, ONE_BINARY)["jobs"]["build-app"]["steps"][-2]["run"]
    assert "windows) (cd \"$stage\" && zip" in run
    assert 'tar -czf "$dist/$base.tar.gz"' in run


@pytest.mark.parametrize(
    "archive, expected, absent",
    [
        ("tar.gz", 'tar -czf "$dist/$base.tar.gz"', "zip -qr"),
        ("zip", "zip -qr", "tar -czf"),
        ("none", 'mv "$stage/$bin" "$dist/$base.exe"', "tar -czf"),
    ],
)
def test_explicit_archive_modes(tmp_path, write_file, archive, expected, absent):
    doc = _doc(
        tmp_path, write_file,
        f"binaries:\n  - name: app\n    archive: {archive}\n",
    )
    run = doc["jobs"]["build-app"]["steps"][-2]["run"]
    assert expected in run
    assert absent not in run


def test_extra_files_are_staged_into_the_archive(tmp_path, write_file):
    doc = _doc(
        tmp_path, write_file,
        "binaries:\n  - name: app\n    extra_files: [ LICENSE, README.md ]\n",
    )
    run = doc["jobs"]["build-app"]["steps"][-2]["run"]
    assert 'cp "$GITHUB_WORKSPACE/LICENSE" "$stage/"' in run
    assert 'cp "$GITHUB_WORKSPACE/README.md" "$stage/"' in run


def test_extra_files_are_dropped_when_nothing_is_archived(tmp_path, write_file):
    """With `archive: none` there is no archive to put them in."""
    doc = _doc(
        tmp_path, write_file,
        "binaries:\n  - name: app\n    archive: none\n    extra_files: [ LICENSE ]\n",
    )
    assert "LICENSE" not in doc["jobs"]["build-app"]["steps"][-2]["run"]


def test_release_job_collects_every_build(tmp_path, write_file):
    doc = _doc(
        tmp_path, write_file,
        "binaries:\n  - name: app\n  - name: appctl\n    package: ./cmd/appctl\n",
    )
    rel = doc["jobs"]["github-release"]
    assert rel["needs"] == ["build-app", "build-appctl"]
    assert rel["permissions"] == {"contents": "write"}
    assert rel["if"] == "github.ref_type == 'tag'"
    assert rel["steps"][0]["with"]["pattern"] == "binaries-*"
    assert rel["steps"][-1]["with"]["files"] == "dist/*"


def test_checksums_do_not_list_themselves(tmp_path, write_file):
    """`sha256sum * > dist/checksums.txt` truncates before the glob expands."""
    run = _doc(tmp_path, write_file, ONE_BINARY)["jobs"]["github-release"]["steps"][1]["run"]
    assert "(cd dist && sha256sum *) > checksums.txt" in run
    assert "mv checksums.txt dist/" in run


def test_no_release_job_without_github_release(tmp_path, write_file):
    """Artifacts alone are still useful; creating a release is a separate decision."""
    head = HEAD.replace("  github_release: true\n", "")
    doc = _doc(tmp_path, write_file, ONE_BINARY, head=head)
    assert "github-release" not in doc["jobs"]
    assert "build-app" in doc["jobs"]


def test_builds_gate_on_the_go_tests(tmp_path, write_file):
    doc = _doc(tmp_path, write_file, ONE_BINARY)
    assert doc["jobs"]["tests"]["uses"] == "./.github/workflows/test-go.yml"
    assert doc["jobs"]["build-app"]["needs"] == ["tests"]


def test_binaries_coexist_with_module_tags(tmp_path, write_file):
    write_file(tmp_path / "sdk/go.mod", "module example.com/repo/sdk\n\ngo 1.25\n")
    write_file(tmp_path / "go.mod", "module example.com/repo\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", '''\
app: 1.2.3
project_rules:
  app:
    - { type: gomod, path: go.mod }
  sdk:
    - { type: gomod, path: sdk/go.mod }
ci:
  github_release: true
  go:
    module_tags: verify
    binaries:
      - name: app
        project: app
        platforms: [ linux/amd64 ]
''')
    cfg = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_publish_go(cfg, cfg.ci))
    assert {"tests", "module-tags", "build-app", "github-release"} <= set(doc["jobs"])
    assert doc["jobs"]["github-release"]["needs"] == ["build-app"]


def test_project_is_required_when_several_modules_exist(tmp_path, write_file):
    """Guessing would build the wrong module and still ship a plausible asset."""
    write_file(tmp_path / "sdk/go.mod", "module example.com/repo/sdk\n\ngo 1.25\n")
    write_file(tmp_path / "go.mod", "module example.com/repo\n\ngo 1.25\n")
    write_file(tmp_path / "versions.yaml", '''\
app: 1.2.3
project_rules:
  app:
    - { type: gomod, path: go.mod }
  sdk:
    - { type: gomod, path: sdk/go.mod }
ci:
  go:
    binaries:
      - name: app
''')
    cfg = load_config(tmp_path / "versions.yaml")
    with pytest.raises(ValueError, match="project is required"):
        build_publish_go(cfg, cfg.ci)


def test_unknown_project_is_an_error(tmp_path, write_file):
    cfg = _cfg(tmp_path, write_file, "binaries:\n  - name: app\n    project: nope\n")
    with pytest.raises(ValueError, match="is not a Go project"):
        build_publish_go(cfg, cfg.ci)


def test_build_runs_in_the_module_directory(tmp_path, write_file):
    # A module with a real dependency, so it has the go.sum the cache keys on.
    write_file(
        tmp_path / "sdk/go.mod",
        "module example.com/repo/sdk\n\ngo 1.25\n\nrequire example.com/dep v1.0.0\n",
    )
    write_file(tmp_path / "sdk/go.sum", "example.com/dep v1.0.0 h1:abc=\n")
    write_file(tmp_path / "versions.yaml", '''\
app: 1.2.3
project_rules:
  sdk:
    - { type: gomod, path: sdk/go.mod }
ci:
  go:
    binaries:
      - name: app
        platforms: [ linux/amd64 ]
''')
    cfg = load_config(tmp_path / "versions.yaml")
    doc = yaml.safe_load(build_publish_go(cfg, cfg.ci))
    step = doc["jobs"]["build-app"]["steps"][-2]
    assert step["working-directory"] == "sdk"
    assert doc["jobs"]["build-app"]["steps"][1]["with"]["cache-dependency-path"] == "sdk/go.sum"


def test_deterministic(tmp_path, write_file):
    assert _doc(tmp_path, write_file, ONE_BINARY) == _doc(tmp_path, write_file, ONE_BINARY)


# ── config validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "block, match",
    [
        ("binaries: []\n", "non-empty list"),
        ("binaries:\n  - package: ./cmd/app\n", "name: required"),
        ("binaries:\n  - name: 'a b'\n", "letters, digits"),
        ("binaries:\n  - name: app\n  - name: app\n", "already declared"),
        ("binaries:\n  - name: app\n    archive: rar\n", "archive: expected one of"),
        ("binaries:\n  - name: app\n    platforms: [ mac/arm64 ]\n", "unknown GOOS"),
        ("binaries:\n  - name: app\n    platforms: [ linux/x86_64 ]\n", "unknown GOARCH"),
        ("binaries:\n  - name: app\n    platforms: [ linux ]\n", "GOOS/GOARCH"),
        ("binaries:\n  - name: app\n    platforms: []\n", "non-empty list"),
        (
            "binaries:\n  - name: app\n    platforms: [ linux/amd64, linux/amd64 ]\n",
            "duplicate platform",
        ),
        ("binaries:\n  - name: app\n    ldflags: '-X main.n=\"x\"'\n", "double quotes"),
        ("binaries:\n  - name: app\n    env:\n      FOO: null\n", "YAML accident"),
        ("binaries:\n  - name: app\n    bulid_args: x\n", "unknown key"),
        ("binary_platforms: [ nope/amd64 ]\nbinaries:\n  - name: app\n", "unknown GOOS"),
    ],
)
def test_config_rejects_bad_binary_descriptors(tmp_path, write_file, block, match):
    with pytest.raises(ConfigError, match=match):
        _cfg(tmp_path, write_file, block)
