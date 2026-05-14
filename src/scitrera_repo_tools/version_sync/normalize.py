"""Version string normalization per target language."""

from __future__ import annotations

OPERATOR_PREFIXES = (">=", "<=", "==", "~=", "!=", ">", "<", "^", "~")


def normalize_python(raw: str) -> str:
    """0.1.22 -> '==0.1.22'; '>=2.10' -> '>=2.10'."""
    s = raw.strip()
    return s if s.startswith(OPERATOR_PREFIXES) else f"=={s}"


def normalize_typescript(raw: str) -> str:
    """Used verbatim; npm accepts '1.2.3', '^1.2.3', '~1.2.3'."""
    return raw.strip()


def normalize_go(raw: str) -> str:
    """Go module versions must start with `v`.

    '1.2.3' -> 'v1.2.3'; 'v1.2.3' -> 'v1.2.3'; pseudo-versions like
    'v0.0.0-20240101120000-abc1234567890' pass through unchanged.
    """
    s = raw.strip()
    return s if s.startswith("v") else f"v{s}"
