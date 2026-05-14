"""Per-strategy basic tests: match, idempotency, missing."""

from __future__ import annotations

import json
from pathlib import Path

from scitrera_repo_tools.version_sync.strategies.go_version import update_go_version
from scitrera_repo_tools.version_sync.strategies.gomod_require import update_gomod_require
from scitrera_repo_tools.version_sync.strategies.init_py import update_init_py
from scitrera_repo_tools.version_sync.strategies.marketplace_json import update_marketplace
from scitrera_repo_tools.version_sync.strategies.package_json import update_json_version
from scitrera_repo_tools.version_sync.strategies.plugin_json import update_plugin
from scitrera_repo_tools.version_sync.strategies.pyproject import update_pyproject


def test_update_pyproject(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
    changed, old = update_pyproject(path, "0.2.0", dry_run=False)
    assert changed and old == "0.1.0"
    assert 'version = "0.2.0"' in path.read_text()

    changed, old = update_pyproject(path, "0.2.0", dry_run=False)
    assert not changed and old == "0.2.0"


def test_update_pyproject_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "x"\n', encoding="utf-8")
    changed, old = update_pyproject(path, "1.0.0", dry_run=False)
    assert changed is False and old is None


def test_update_init_py(tmp_path: Path) -> None:
    path = tmp_path / "__init__.py"
    path.write_text("__version__ = '0.1.0'\n", encoding="utf-8")
    changed, old = update_init_py(path, "0.2.0", dry_run=False)
    assert changed and old == "0.1.0"
    assert path.read_text() == "__version__ = '0.2.0'\n"

    changed, old = update_init_py(path, "0.2.0", dry_run=False)
    assert not changed and old == "0.2.0"


def test_update_init_py_missing(tmp_path: Path) -> None:
    path = tmp_path / "__init__.py"
    path.write_text("# nothing here\n", encoding="utf-8")
    changed, old = update_init_py(path, "1.0.0", dry_run=False)
    assert changed is False and old is None


def test_update_json_version(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    path.write_text(json.dumps({"name": "x", "version": "0.1.0"}) + "\n", encoding="utf-8")
    changed, old = update_json_version(path, "0.2.0", dry_run=False)
    assert changed and old == "0.1.0"
    data = json.loads(path.read_text())
    assert data["version"] == "0.2.0"

    changed, old = update_json_version(path, "0.2.0", dry_run=False)
    assert not changed and old == "0.2.0"


def test_update_plugin(tmp_path: Path) -> None:
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps({"name": "p", "version": "0.1.0"}), encoding="utf-8")
    changed, old = update_plugin(path, "0.2.0", dry_run=False)
    assert changed and old == "0.1.0"


def test_update_marketplace(tmp_path: Path) -> None:
    path = tmp_path / "marketplace.json"
    path.write_text(
        json.dumps({"plugins": [{"source": "my-plugin-dir", "version": "0.0.1"}]}),
        encoding="utf-8",
    )
    changed, old = update_marketplace(path, "0.2.0", dry_run=False, project_dir="my-plugin-dir")
    assert changed and old == "0.0.1"
    data = json.loads(path.read_text())
    assert data["plugins"][0]["version"] == "0.2.0"


def test_update_marketplace_no_match(tmp_path: Path) -> None:
    path = tmp_path / "marketplace.json"
    path.write_text(
        json.dumps({"plugins": [{"source": "other", "version": "0.0.1"}]}),
        encoding="utf-8",
    )
    changed, old = update_marketplace(path, "0.2.0", dry_run=False, project_dir="not-here")
    assert changed is False and old is None


def test_update_go_version(tmp_path: Path) -> None:
    path = tmp_path / "version.go"
    path.write_text(
        'package version\n\nconst Version = "0.1.0"\n',
        encoding="utf-8",
    )
    changed, old = update_go_version(path, "0.2.0", dry_run=False)
    assert changed and old == "0.1.0"
    assert 'const Version = "0.2.0"' in path.read_text()


def test_update_gomod_require(tmp_path: Path) -> None:
    path = tmp_path / "go.mod"
    path.write_text(
        '''\
module example.com/myapp

go 1.22

require (
\tgithub.com/scitrera/aether/api v0.1.0
\tgithub.com/other/lib v1.2.3
)

replace github.com/scitrera/aether/api => ../api
''',
        encoding="utf-8",
    )
    changed, old = update_gomod_require(
        path, "0.2.0", dry_run=False, target_module="github.com/scitrera/aether/api"
    )
    assert changed and old == "0.1.0"
    assert "github.com/scitrera/aether/api v0.2.0" in path.read_text()
    assert "github.com/other/lib v1.2.3" in path.read_text()


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    original = '[project]\nname = "x"\nversion = "0.1.0"\n'
    path.write_text(original, encoding="utf-8")
    changed, old = update_pyproject(path, "0.2.0", dry_run=True)
    assert changed and old == "0.1.0"
    assert path.read_text() == original
