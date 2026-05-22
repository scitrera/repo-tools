"""Regression: pyproject dep rewriter must not partial-match name prefixes.

Background: `preferred_versions.python.pytest: 9.0.3` was rewriting
`pytest-asyncio>=0.23` to `pytest==9.0.3` because the regex name match did
not require a PEP 508 name-boundary after the escaped name.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

from scitrera_repo_tools.version_sync.strategies.pyproject import (
    rewrite_pyproject_dep,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_pytest_does_not_match_pytest_asyncio(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    _write(
        pp,
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "pytest-asyncio>=0.23",\n'
        ']\n',
    )

    changed, old = rewrite_pyproject_dep(pp, "pytest", "==9.0.3", dry_run=False)
    assert changed is False
    assert old is None
    assert '"pytest-asyncio>=0.23"' in pp.read_text()


def test_exact_pytest_match_still_rewrites(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    _write(
        pp,
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "pytest>=7.0",\n'
        '    "pytest-asyncio>=0.23",\n'
        '    "pytest-cov>=4.0",\n'
        ']\n',
    )

    changed, old = rewrite_pyproject_dep(pp, "pytest", "==9.0.3", dry_run=False)
    assert changed is True
    assert old == ">=7.0"

    text = pp.read_text()
    assert '"pytest==9.0.3"' in text
    assert '"pytest-asyncio>=0.23"' in text
    assert '"pytest-cov>=4.0"' in text


def test_extras_form_still_matches(tmp_path: Path) -> None:
    pp = tmp_path / "pyproject.toml"
    _write(
        pp,
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "pytest[extra]>=7.0",\n'
        ']\n',
    )

    changed, _ = rewrite_pyproject_dep(pp, "pytest", "==9.0.3", dry_run=False)
    assert changed is True
    assert '"pytest[extra]==9.0.3"' in pp.read_text()


def test_name_with_dot_and_underscore_boundary(tmp_path: Path) -> None:
    """Dotted/underscored extensions of the name must also be left alone."""
    pp = tmp_path / "pyproject.toml"
    _write(
        pp,
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "foo.bar>=1.0",\n'
        '    "foo_baz>=2.0",\n'
        '    "foo9>=3.0",\n'
        ']\n',
    )

    changed, _ = rewrite_pyproject_dep(pp, "foo", "==1.2.3", dry_run=False)
    assert changed is False
    text = pp.read_text()
    assert '"foo.bar>=1.0"' in text
    assert '"foo_baz>=2.0"' in text
    assert '"foo9>=3.0"' in text
