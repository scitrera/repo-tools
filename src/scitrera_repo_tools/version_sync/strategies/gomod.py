"""go.mod module-declaration strategy.

Unlike every other strategy in this package, this one rewrites nothing. A
`gomod` rule answers a question no other rule can: *which directory is this
project's Go module?*

For Python and TypeScript that question answers itself — `pyproject.toml` and
`package.json` are both the file a version gets written into and the root of the
thing CI builds. Go has no version manifest at all: a module's version lives in
a git tag, so the only go.mod rule that existed (`gomod_require`) is about
pinning *other* modules' require lines. Those two facts come apart badly:

  - a module with no in-repo requires has no `gomod_require` rule, so nothing
    identifies it and CI never sees it;
  - a project whose only `gomod_require` targets a *nested* module gets its
    entire Go lane pointed at the wrong directory — tests run against the wrong
    module, and `publish-go` reconciles a tag nobody resolves against.

Declaring the module explicitly separates "where I rewrite pins" from "what I
am", which is the distinction the single-rule model was silently collapsing.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("scitrera_repo_tools.version_sync")


def declare_gomod(
    path: Path,
    version: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    """Declare `path` as this project's Go module. Never modifies the file.

    Deliberately still a rule rather than a `ci:` setting: the module layout is
    a fact about the repository, not a CI preference, so it belongs where the
    other facts about a project's files are declared.
    """
    del version, dry_run  # a declaration has nothing to write
    if not path.exists():
        logger.warning("Declared Go module not found: %s", path)
    return False, None


__all__ = ["declare_gomod"]
