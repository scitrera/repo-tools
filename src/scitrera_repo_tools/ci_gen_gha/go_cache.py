"""Whether a Go module's setup-go step can cache, and whether it must.

`actions/setup-go` caches the module download directory keyed on a checksum
file. Pointing `cache-dependency-path` at a `go.sum` that does not exist is not
a cache miss — the action fails the step outright with "Some specified paths
were not resolved, unable to cache dependencies", so every Go job in the repo
goes red before it compiles anything.

A module can legitimately have no `go.sum`: Go writes checksums only for
dependencies it downloads, so a module that requires nothing external (or whose
every requirement is redirected to a local directory by a `replace`) has no
checksums to record and never gets the file. The distinction matters because
the other reason `go.sum` goes missing is that someone forgot to commit it —
and that module genuinely cannot build from a clean checkout. Emitting
`cache: false` for it would trade a clear failure at generation time for a
confusing one during `go build`, so the two cases are told apart here rather
than collapsed into "no file, no cache".
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import re
from pathlib import Path
from typing import Set, Tuple

# go.mod comments run to end of line and cannot be escaped or nested, so
# stripping them wholesale is safe — unlike in a language with string literals.
_COMMENT_RE = re.compile(r"//.*$", re.MULTILINE)

# A `replace` target is a local directory rather than a module path when it
# looks like a filesystem path. Go requires exactly this shape: the right-hand
# side must start with `./`, `../`, or be absolute, otherwise it is a module.
_LOCAL_PATH_RE = re.compile(r"^(\.{1,2}[\\/]|[\\/]|[A-Za-z]:[\\/])")


def _consume(directive: str, line: str, requires: Set[str], replaced: Set[str]) -> None:
    if directive == "require":
        parts = line.split()
        if parts:
            requires.add(parts[0])
        return

    # `replace old [vX] => new [vY]`; only the left module path matters, and
    # only when the right-hand side is a local directory.
    left, sep, right = line.partition("=>")
    if not sep:
        return
    old = left.split()
    new = right.split()
    if old and new and _LOCAL_PATH_RE.match(new[0]):
        replaced.add(old[0])


def parse_gomod_deps(text: str) -> Tuple[Set[str], Set[str]]:
    """Return (required module paths, module paths replaced by a local directory)."""
    requires: Set[str] = set()
    replaced: Set[str] = set()
    block = ""

    for raw in _COMMENT_RE.sub("", text).splitlines():
        line = raw.strip()
        if not line:
            continue

        if block:
            if line.startswith(")"):
                block = ""
                continue
            _consume(block, line, requires, replaced)
            continue

        for directive in ("require", "replace"):
            if line == directive or line.startswith(directive + " ") or line.startswith(directive + "("):
                rest = line[len(directive):].strip()
                if rest.startswith("("):
                    block = directive
                    rest = rest[1:].strip()
                    if rest and not rest.startswith(")"):
                        _consume(directive, rest, requires, replaced)
                elif rest:
                    _consume(directive, rest, requires, replaced)
                break

    return requires, replaced


def module_needs_checksums(gomod_path: Path) -> bool:
    """True when Go must verify this module against a `go.sum`.

    False only when nothing is downloaded: no requirements at all, or every
    requirement redirected to a local directory. Transitive dependencies of a
    locally-replaced module still appear in this `go.mod` as indirect
    requirements, so they are counted here too.
    """
    try:
        text = gomod_path.read_text(encoding="utf-8")
    except OSError:
        # A missing or unreadable go.mod is already reported by the `gomod`
        # rule itself; re-raising here would bury that message under a second.
        return False

    requires, replaced = parse_gomod_deps(text)
    return bool(requires - replaced)


def go_cache_with(root: Path, project: str, project_dir: str, indent: str = "          ") -> str:
    """Render the setup-go cache inputs for one module.

    Raises when the module has downloads to verify but no committed `go.sum`,
    which is a broken checkout rather than a CI-configuration choice.
    """
    module_dir = root / project_dir
    gosum = module_dir / "go.sum"
    if gosum.is_file():
        return f"{indent}cache-dependency-path: {project_dir}/go.sum"

    if module_needs_checksums(module_dir / "go.mod"):
        raise ValueError(
            f"Go project '{project}': {project_dir}/go.mod requires external "
            f"module(s) but {project_dir}/go.sum is missing, so a clean "
            f"checkout cannot build or verify them. Run `go mod tidy` in "
            f"{project_dir}/ and commit the resulting go.sum."
        )

    # Nothing to download means nothing to cache, and no checksum file for
    # setup-go to key on. Disable the cache outright rather than let the action
    # fail on an unresolvable path.
    return f"{indent}cache: false"


__all__ = ["go_cache_with", "module_needs_checksums", "parse_gomod_deps"]
