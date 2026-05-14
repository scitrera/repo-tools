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
