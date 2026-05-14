"""Tests for preferred_versions rewriters (Phase C semantics)."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from scitrera_repo_tools.version_sync.strategies.gomod_require import (
    rewrite_gomod_require,
)
from scitrera_repo_tools.version_sync.strategies.package_json import (
    rewrite_package_json_dep,
)
from scitrera_repo_tools.version_sync.strategies.pyproject import (
    rewrite_pyproject_dep,
)


def test_rewrite_pyproject_dep_updates_existing(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        dedent(
            '''\
            [project]
            name = "x"
            dependencies = [
                "pydantic>=2.0",
                "fastapi==0.100.0",
            ]
            '''
        ),
        encoding="utf-8",
    )
    changed, old = rewrite_pyproject_dep(path, "pydantic", "==2.13.4", dry_run=False)
    assert changed
    assert old == ">=2.0"
    text = path.read_text()
    assert '"pydantic==2.13.4"' in text
    assert '"fastapi==0.100.0"' in text


def test_rewrite_pyproject_dep_with_extras(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        '[project]\ndependencies = [\n    "sqlalchemy[asyncio]==2.0.0",\n]\n',
        encoding="utf-8",
    )
    changed, old = rewrite_pyproject_dep(path, "sqlalchemy[asyncio]", "==2.0.46", dry_run=False)
    assert changed and old == "==2.0.0"
    assert '"sqlalchemy[asyncio]==2.0.46"' in path.read_text()


def test_rewrite_pyproject_dep_no_inject(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    original = '[project]\ndependencies = ["fastapi==0.100.0"]\n'
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_pyproject_dep(path, "pydantic", "==2.13.4", dry_run=False)
    assert not changed and old is None
    assert path.read_text() == original


def test_rewrite_pyproject_dep_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        '[project]\ndependencies = ["pydantic==2.13.4"]\n',
        encoding="utf-8",
    )
    changed, _ = rewrite_pyproject_dep(path, "pydantic", "==2.13.4", dry_run=False)
    assert not changed


def test_rewrite_package_json_dep(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    path.write_text(
        json.dumps(
            {
                "name": "@x/y",
                "version": "0.1.0",
                "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0"},
                "devDependencies": {"typescript": "5.0.0"},
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    changed, old = rewrite_package_json_dep(
        path, "@modelcontextprotocol/sdk", "^1.26.0", dry_run=False
    )
    assert changed and old == "^1.0.0"
    data = json.loads(path.read_text())
    assert data["dependencies"]["@modelcontextprotocol/sdk"] == "^1.26.0"
    assert data["devDependencies"]["typescript"] == "5.0.0"


def test_rewrite_package_json_dep_no_inject(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    original = json.dumps(
        {"name": "x", "version": "0.1.0", "dependencies": {"foo": "1.0.0"}}, indent=2
    ) + "\n"
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_package_json_dep(path, "missing", "^2.0.0", dry_run=False)
    assert not changed and old is None
    assert path.read_text() == original


def test_rewrite_package_json_dep_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    original = json.dumps(
        {"name": "x", "version": "0.1.0", "dependencies": {"foo": "1.0.0"}}, indent=2
    ) + "\n"
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_package_json_dep(path, "foo", "^2.0.0", dry_run=True)
    assert changed and old == "1.0.0"
    assert path.read_text() == original


def test_rewrite_package_json_dep_skips_workspace_specifiers(tmp_path: Path) -> None:
    """workspace/file/link/git/url specifiers must be preserved verbatim."""
    path = tmp_path / "package.json"
    original = json.dumps(
        {
            "name": "x",
            "version": "0.1.0",
            "dependencies": {
                "@scitrera/foo": "file:../foo",
                "@scitrera/bar": "workspace:*",
                "@scitrera/baz": "link:../baz",
                "ghpkg": "github:user/repo#v1",
                "gitpkg": "git+https://github.com/user/repo.git",
                "urlpkg": "https://example.com/pkg.tgz",
            },
        },
        indent=2,
    ) + "\n"
    path.write_text(original, encoding="utf-8")
    for name in ("@scitrera/foo", "@scitrera/bar", "@scitrera/baz", "ghpkg", "gitpkg", "urlpkg"):
        changed, old = rewrite_package_json_dep(path, name, "1.2.3", dry_run=False)
        assert not changed, f"{name} should have been skipped"
        assert old is None
    assert path.read_text() == original


def test_rewrite_pyproject_dep_skips_direct_reference(tmp_path: Path) -> None:
    """PEP 508 direct-reference deps (`pkg @ git+...`) must be preserved verbatim."""
    path = tmp_path / "pyproject.toml"
    original = (
        '[project]\n'
        'dependencies = [\n'
        '    "foo @ git+https://github.com/user/foo.git",\n'
        '    "bar @ file:///tmp/bar",\n'
        ']\n'
    )
    path.write_text(original, encoding="utf-8")
    for name in ("foo", "bar"):
        changed, _ = rewrite_pyproject_dep(path, name, "==1.2.3", dry_run=False)
        assert not changed, f"{name} should have been skipped"
    assert path.read_text() == original


def test_rewrite_package_json_dep_release_mode_rewrites_local_refs(tmp_path: Path) -> None:
    """`resolve_local_refs=True` (release mode) MUST rewrite workspace/file/etc."""
    path = tmp_path / "package.json"
    original = json.dumps(
        {
            "name": "x",
            "version": "0.1.0",
            "dependencies": {
                "@scitrera/foo": "file:../foo",
                "@scitrera/bar": "workspace:*",
                "@scitrera/baz": "link:../baz",
            },
        },
        indent=2,
    ) + "\n"
    path.write_text(original, encoding="utf-8")
    for name, old in (
        ("@scitrera/foo", "file:../foo"),
        ("@scitrera/bar", "workspace:*"),
        ("@scitrera/baz", "link:../baz"),
    ):
        changed, returned_old = rewrite_package_json_dep(
            path, name, "0.1.22", dry_run=False, resolve_local_refs=True
        )
        assert changed, f"{name} should have been rewritten in release mode"
        assert returned_old == old
    data = json.loads(path.read_text())
    assert data["dependencies"]["@scitrera/foo"] == "0.1.22"
    assert data["dependencies"]["@scitrera/bar"] == "0.1.22"
    assert data["dependencies"]["@scitrera/baz"] == "0.1.22"


def test_rewrite_pyproject_dep_release_mode_rewrites_direct_reference(tmp_path: Path) -> None:
    """`resolve_local_refs=True` rewrites PEP 508 `pkg @ git+...` into a version pin."""
    path = tmp_path / "pyproject.toml"
    original = (
        '[project]\n'
        'dependencies = [\n'
        '    "foo @ git+https://github.com/user/foo.git",\n'
        '    "bar @ file:///tmp/bar",\n'
        ']\n'
    )
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_pyproject_dep(
        path, "foo", "==1.2.3", dry_run=False, resolve_local_refs=True
    )
    assert changed
    assert old == "@ git+https://github.com/user/foo.git"
    text = path.read_text()
    assert '"foo==1.2.3"' in text, text
    # bar should be untouched (we only rewrote foo here)
    assert '"bar @ file:///tmp/bar"' in text


def test_rewrite_package_json_dep_default_still_skips_workspace(tmp_path: Path) -> None:
    """Without resolve_local_refs, workspace specifiers are still preserved (regression guard)."""
    path = tmp_path / "package.json"
    original = json.dumps(
        {"name": "x", "version": "0.1.0", "dependencies": {"@scitrera/foo": "workspace:*"}},
        indent=2,
    ) + "\n"
    path.write_text(original, encoding="utf-8")
    changed, _ = rewrite_package_json_dep(path, "@scitrera/foo", "0.1.22", dry_run=False)
    assert not changed
    assert path.read_text() == original


def test_rewrite_gomod_require_updates_existing(tmp_path: Path) -> None:
    path = tmp_path / "go.mod"
    path.write_text(
        'module example.com/x\n\ngo 1.21\n\nrequire (\n'
        '\tgoogle.golang.org/grpc v1.60.0\n'
        '\tgoogle.golang.org/protobuf v1.33.0\n'
        ')\n',
        encoding="utf-8",
    )
    changed, old = rewrite_gomod_require(path, "google.golang.org/grpc", "v1.65.0", dry_run=False)
    assert changed and old == "v1.60.0"
    text = path.read_text()
    assert "google.golang.org/grpc v1.65.0" in text
    assert "google.golang.org/protobuf v1.33.0" in text


def test_rewrite_gomod_require_accepts_bare_version(tmp_path: Path) -> None:
    """A version string without leading `v` should still work."""
    path = tmp_path / "go.mod"
    path.write_text(
        "module example.com/x\n\nrequire google.golang.org/grpc v1.60.0\n",
        encoding="utf-8",
    )
    changed, old = rewrite_gomod_require(path, "google.golang.org/grpc", "1.65.0", dry_run=False)
    assert changed and old == "v1.60.0"
    assert "google.golang.org/grpc v1.65.0" in path.read_text()


def test_rewrite_gomod_require_no_inject(tmp_path: Path) -> None:
    """If the module isn't already required, do nothing."""
    path = tmp_path / "go.mod"
    original = "module example.com/x\n\nrequire google.golang.org/grpc v1.60.0\n"
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_gomod_require(path, "missing/module", "v1.0.0", dry_run=False)
    assert not changed and old is None
    assert path.read_text() == original


def test_rewrite_gomod_require_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "go.mod"
    path.write_text(
        "module example.com/x\n\nrequire google.golang.org/grpc v1.65.0\n",
        encoding="utf-8",
    )
    changed, _ = rewrite_gomod_require(path, "google.golang.org/grpc", "v1.65.0", dry_run=False)
    assert not changed


def test_rewrite_gomod_require_ignores_replace_directive(tmp_path: Path) -> None:
    """`replace` lines must not be matched by the require regex."""
    path = tmp_path / "go.mod"
    original = (
        "module example.com/x\n\n"
        "require google.golang.org/grpc v1.60.0\n\n"
        "replace google.golang.org/grpc => ../grpc-fork\n"
    )
    path.write_text(original, encoding="utf-8")
    changed, old = rewrite_gomod_require(path, "google.golang.org/grpc", "v1.65.0", dry_run=False)
    assert changed and old == "v1.60.0"
    text = path.read_text()
    assert "require google.golang.org/grpc v1.65.0" in text
    assert "replace google.golang.org/grpc => ../grpc-fork" in text, "replace must be untouched"
