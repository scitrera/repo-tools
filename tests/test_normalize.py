"""Tests for normalize.py."""

from __future__ import annotations

import pytest

from scitrera_repo_tools.version_sync.normalize import (
    normalize_go,
    normalize_python,
    normalize_typescript,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.1.22", "==0.1.22"),
        ("1.0.0", "==1.0.0"),
        (">=2.10", ">=2.10"),
        ("<=3.0.0", "<=3.0.0"),
        ("==1.2.3", "==1.2.3"),
        ("~=1.0", "~=1.0"),
        ("!=1.0", "!=1.0"),
        (">1.0", ">1.0"),
        ("<2.0", "<2.0"),
        ("^1.2.3", "^1.2.3"),
        ("~1.2.3", "~1.2.3"),
    ],
)
def test_normalize_python(raw: str, expected: str) -> None:
    assert normalize_python(raw) == expected


def test_normalize_python_strips_whitespace() -> None:
    assert normalize_python("  0.1.22  ") == "==0.1.22"
    assert normalize_python("  >=1.0  ") == ">=1.0"


@pytest.mark.parametrize(
    "raw",
    ["1.2.3", "^1.2.3", "~1.2.3", ">=2.0.0"],
)
def test_normalize_typescript_verbatim(raw: str) -> None:
    assert normalize_typescript(raw) == raw


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.2.3", "v1.2.3"),
        ("v1.2.3", "v1.2.3"),
        ("0.1.60", "v0.1.60"),
        ("v0.1.60", "v0.1.60"),
        ("v1.2.3-rc.1", "v1.2.3-rc.1"),
        ("v0.0.0-20240101120000-abc1234567890", "v0.0.0-20240101120000-abc1234567890"),
    ],
)
def test_normalize_go(raw: str, expected: str) -> None:
    assert normalize_go(raw) == expected


def test_normalize_go_strips_whitespace() -> None:
    assert normalize_go("  1.2.3  ") == "v1.2.3"
    assert normalize_go("  v1.2.3  ") == "v1.2.3"
