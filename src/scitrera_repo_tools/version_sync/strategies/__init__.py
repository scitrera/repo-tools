"""Registry of project-version sync strategies."""

from __future__ import annotations

from typing import Callable, Dict

from .go_version import update_go_version
from .gomod import declare_gomod
from .gomod_require import update_gomod_require
from .init_py import update_init_py
from .marketplace_json import update_marketplace
from .package_json import update_json_version
from .plugin_json import update_plugin
from .pyproject import update_pyproject

STRATEGY_MAP: Dict[str, Callable] = {
    "pyproject": update_pyproject,
    "init_py": update_init_py,
    "package": update_json_version,
    "plugin": update_plugin,
    "marketplace": update_marketplace,
    "go_version": update_go_version,
    "gomod": declare_gomod,
    "gomod_require": update_gomod_require,
}

__all__ = ["STRATEGY_MAP"]
