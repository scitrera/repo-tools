"""The `gomod` rule: declaring which directory is a project's Go module.

Go has no version manifest — a module's version is a git tag — so the only
go.mod rule that existed (`gomod_require`) is about pinning *other* modules'
require lines. Discovery leaned on it anyway, which silently pointed a project's
whole Go lane at whatever file that rule happened to name.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import yaml

from scitrera_repo_tools.ci_gen_gha.templates import build_publish_go, build_test_go
from scitrera_repo_tools.version_sync.config import load_config
from scitrera_repo_tools.version_sync.discovery import manifests_for_language
from scitrera_repo_tools.version_sync.runner import run

# A parent module with no in-repo requires, plus a nested module that requires
# it — the shape that has no `gomod_require` rule to identify the parent.
NESTED = """\
sdk-go: 0.1.0

project_rules:
  sdk-go:
{rules}
"""


def _repo(tmp_path: Path, write_file, rules: str) -> Path:
    write_file(tmp_path / "sdk-go/go.mod", "module example.com/repo/sdk-go\n\ngo 1.23\n")
    write_file(tmp_path / "sdk-go/go.sum", "")
    write_file(
        tmp_path / "sdk-go/aether/go.mod",
        "module example.com/repo/sdk-go/aether\n\ngo 1.23\n\n"
        "require example.com/repo/sdk-go v0.1.0\n",
    )
    write_file(tmp_path / "sdk-go/aether/go.sum", "")
    write_file(tmp_path / "sdk-go/doc.go", 'package sdk\n\nconst Version = "0.1.0"\n')
    write_file(tmp_path / "versions.yaml", NESTED.format(rules=rules))
    return tmp_path


REQUIRE_ONLY = (
    "    - { type: go_version,    path: sdk-go/doc.go }\n"
    "    - { type: gomod_require, path: sdk-go/aether/go.mod,"
    " args: [ example.com/repo/sdk-go ] }\n"
)
WITH_GOMOD = (
    "    - { type: go_version,    path: sdk-go/doc.go }\n"
    "    - { type: gomod_require, path: sdk-go/aether/go.mod,"
    " args: [ example.com/repo/sdk-go ] }\n"
    "    - { type: gomod,         path: sdk-go/go.mod }\n"
)


def _dirs(text: str) -> set:
    jobs = yaml.safe_load(text)["jobs"]
    return {
        s["working-directory"]
        for job in jobs.values()
        for s in job["steps"]
        if "working-directory" in s
    }


def test_without_gomod_the_nested_module_is_mistaken_for_the_project(tmp_path, write_file):
    """Documents the old behavior the `gomod` rule exists to correct."""
    cfg = load_config(_repo(tmp_path, write_file, REQUIRE_ONLY) / "versions.yaml")
    assert _dirs(build_test_go(cfg, cfg.ci)) == {"sdk-go/aether"}


def test_gomod_identifies_the_project_module(tmp_path, write_file):
    cfg = load_config(_repo(tmp_path, write_file, WITH_GOMOD) / "versions.yaml")
    assert _dirs(build_test_go(cfg, cfg.ci)) == {"sdk-go"}


def test_gomod_wins_regardless_of_declaration_order(tmp_path, write_file):
    """Precedence is by rule type, not by position in the list."""
    reordered = (
        "    - { type: gomod,         path: sdk-go/go.mod }\n"
        "    - { type: gomod_require, path: sdk-go/aether/go.mod,"
        " args: [ example.com/repo/sdk-go ] }\n"
    )
    a = load_config(_repo(tmp_path, write_file, WITH_GOMOD) / "versions.yaml")
    b = load_config(_repo(tmp_path, write_file, reordered) / "versions.yaml")
    assert manifests_for_language(a, "go") == manifests_for_language(b, "go")


def test_publish_go_tags_the_declared_module(tmp_path, write_file):
    """The tag `go get` resolves against is the module's own, not a submodule's."""
    root = _repo(tmp_path, write_file, WITH_GOMOD)
    text = (root / "versions.yaml").read_text() + "ci:\n  go:\n    module_tags: verify\n"
    (root / "versions.yaml").write_text(text)
    cfg = load_config(root / "versions.yaml")
    assert 'MODULE_DIRS: "sdk-go"' in build_publish_go(cfg, cfg.ci)


def test_gomod_require_still_identifies_when_no_gomod_rule(tmp_path, write_file):
    """Backwards compatibility: repos predating `gomod` keep their behavior."""
    write_file(tmp_path / "mod/go.mod", "module example.com/repo/mod\n")
    write_file(tmp_path / "mod/go.sum", "")
    write_file(
        tmp_path / "versions.yaml",
        "m: 0.1.0\nproject_rules:\n  m:\n"
        "    - { type: gomod_require, path: mod/go.mod, args: [ example.com/dep ] }\n",
    )
    cfg = load_config(tmp_path / "versions.yaml")
    assert _dirs(build_test_go(cfg, cfg.ci)) == {"mod"}


def test_gomod_is_a_declaration_and_never_writes(tmp_path, write_file):
    """sync-versions must not treat the declaration as something to rewrite."""
    root = _repo(tmp_path, write_file, WITH_GOMOD)
    before = (root / "sdk-go/go.mod").read_text()
    cfg = load_config(root / "versions.yaml")

    assert run(cfg, check=False, verbose=False, release=False) == 0
    assert (root / "sdk-go/go.mod").read_text() == before
    # And the version-bearing rules in the same project still applied.
    assert 'const Version = "0.1.0"' in (root / "sdk-go/doc.go").read_text()
