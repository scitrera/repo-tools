"""The go_version rule accepts both Go version-declaration idioms."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.version_sync.strategies.go_version import update_go_version


def _apply(tmp_path: Path, source: str, version: str = "0.2.0"):
    path = tmp_path / "version.go"
    path.write_text(source, encoding="utf-8")
    changed, old = update_go_version(path, version, dry_run=False)
    return changed, old, path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "decl,expected",
    [
        ('const Version = "0.1.0"', 'const Version = "0.2.0"'),
        # The ldflags idiom: `-X main.version=...` overrides at build time, but
        # the baked default is what `go install` and local builds report.
        ('var version = "0.1.0"', 'var version = "0.2.0"'),
        ('var Version = "0.1.0"', 'var Version = "0.2.0"'),
        ('const version = "0.1.0"', 'const version = "0.2.0"'),
        ('var version string = "0.1.0"', 'var version string = "0.2.0"'),
        ('\tconst Version = "0.1.0"', '\tconst Version = "0.2.0"'),
    ],
)
def test_recognised_forms(tmp_path: Path, decl: str, expected: str) -> None:
    changed, old, text = _apply(tmp_path, f"package main\n\n{decl}\n")
    assert changed is True
    assert old == "0.1.0"
    assert expected in text


def test_already_current_is_not_a_change(tmp_path: Path) -> None:
    changed, old, _ = _apply(tmp_path, 'package main\n\nvar version = "0.2.0"\n')
    assert changed is False
    assert old == "0.2.0"


@pytest.mark.parametrize(
    "decl",
    [
        # Not a version declaration: the name only starts with "version".
        'var versionString = "0.1.0"',
        'const VersionPrefix = "0.1.0"',
        # A different identifier entirely.
        'var release = "0.1.0"',
    ],
)
def test_similar_identifiers_are_not_rewritten(tmp_path: Path, decl: str) -> None:
    changed, old, text = _apply(tmp_path, f"package main\n\n{decl}\n")
    assert changed is False
    assert old is None
    assert "0.1.0" in text


def test_const_version_wins_over_an_earlier_var(tmp_path: Path) -> None:
    """Back-compat: `const Version` was the only form this rule ever matched.

    A file declaring both must keep targeting the const, or upgrading repo-tools
    would silently retarget an existing rule onto a different line.
    """
    changed, old, text = _apply(
        tmp_path,
        'package main\n\nvar version = "0.1.0"\n\nconst Version = "9.9.9"\n',
    )
    assert changed is True
    assert old == "9.9.9"
    assert 'const Version = "0.2.0"' in text
    assert 'var version = "0.1.0"' in text


def test_only_the_first_declaration_is_rewritten(tmp_path: Path) -> None:
    """count=1 keeps an unrelated later match of the same form from being clobbered."""
    changed, _, text = _apply(
        tmp_path,
        'package main\n\nvar version = "0.1.0"\n\nvar Version = "9.9.9"\n',
    )
    assert changed is True
    assert 'var version = "0.2.0"' in text
    assert 'var Version = "9.9.9"' in text
