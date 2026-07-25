"""Orchestrate generate-vs-disk diff + write for the `generate-ci-gha` subcommand."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import difflib
import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List

from ..version_sync.config import SyncConfig
from .templates import WORKFLOW_GENERATORS, render_all

logger = logging.getLogger("scitrera_repo_tools.ci_gen_gha")


class State(str, Enum):
    OK = "ok"            # file on disk matches the generator
    MISSING = "missing"  # file would be created
    DRIFT = "drift"      # file on disk differs


@dataclass(frozen=True)
class FileResult:
    filename: str
    state: State
    desired: str
    existing: str  # "" when missing


def _classify(workflows_dir: Path, rendered: Dict[str, str]) -> List[FileResult]:
    results: List[FileResult] = []
    for filename, desired in rendered.items():
        path = workflows_dir / filename
        if not desired:
            # Generator produced empty (e.g. no python projects) → skip entirely.
            continue
        if not path.exists():
            results.append(FileResult(filename, State.MISSING, desired, ""))
            continue
        existing = path.read_text(encoding="utf-8")
        if existing == desired:
            results.append(FileResult(filename, State.OK, desired, existing))
        else:
            results.append(FileResult(filename, State.DRIFT, desired, existing))
    return results


def _print_diff(result: FileResult) -> None:
    diff = difflib.unified_diff(
        result.existing.splitlines(keepends=True),
        result.desired.splitlines(keepends=True),
        fromfile=f"a/{result.filename}",
        tofile=f"b/{result.filename}",
        n=3,
    )
    sys.stdout.write("".join(diff))


def run(
    config: SyncConfig,
    *,
    workflows_dir: Path,
    force: bool,
    check_only: bool,
) -> int:
    """Execute generate-ci-gha.

    Semantics:
    - First pass through `_classify`: bucket each workflow into ok / missing / drift.
    - When `check_only` is True, never writes anything; exits 1 if missing or drift.
    - When `force` is True, writes both missing and drift files.
    - Default (neither flag): writes only missing files, prints diff for drift,
      exits 1 if any drift exists. This makes the no-flag invocation safe to
      run repeatedly (first time creates, subsequent times check).
    """
    rendered = render_all(config)

    known = {name[: -len(".yml")] for name, _ in WORKFLOW_GENERATORS}
    unknown = sorted(set(config.ci.only_workflows) - known)
    if unknown:
        # A typo here would silently manage nothing at all, so it is an error
        # rather than an empty allowlist that looks like success.
        logger.error(
            "ci.only_workflows names unknown workflow(s) %s; expected one of %s",
            unknown, sorted(known),
        )
        return 2

    # Honor ci.only_workflows — an allowlist, so a repo adopting one generated
    # workflow at a time doesn't have to enumerate every workflow it *doesn't*
    # want and revisit that list whenever a new generator is added.
    only = {f"{n}.yml" for n in config.ci.only_workflows}
    excluded: List[str] = []
    if only:
        # Only report entries that would actually have produced a file; listing
        # workflows the repo has no projects for is noise, not information.
        excluded = sorted(k for k, v in rendered.items() if v and k not in only)
        rendered = {k: v for k, v in rendered.items() if k in only}

    # Honor ci.skip_workflows — drop those entries entirely so the generator
    # doesn't manage them. The on-disk file (if any) is left untouched. Applied
    # after the allowlist, so skip still subtracts from an explicit selection.
    skip = {f"{n}.yml" for n in config.ci.skip_workflows}
    skipped = sorted(set(rendered).intersection(skip))
    rendered = {k: v for k, v in rendered.items() if k not in skip}

    results = _classify(workflows_dir, rendered)
    for filename in excluded:
        logger.info("  %-22s not in ci.only_workflows", filename)
    for filename in skipped:
        logger.info("  %-22s skipped (ci.skip_workflows)", filename)

    missing = [r for r in results if r.state is State.MISSING]
    drift = [r for r in results if r.state is State.DRIFT]
    ok = [r for r in results if r.state is State.OK]

    workflows_dir.mkdir(parents=True, exist_ok=True)

    wrote: List[str] = []

    if not check_only:
        for r in missing:
            (workflows_dir / r.filename).write_text(r.desired, encoding="utf-8")
            wrote.append(r.filename)

    if force and not check_only:
        for r in drift:
            (workflows_dir / r.filename).write_text(r.desired, encoding="utf-8")
            wrote.append(r.filename)

    # Report.
    for r in ok:
        logger.info("  %-22s in sync", r.filename)
    for r in missing:
        if check_only:
            logger.info("  %-22s would be created", r.filename)
        else:
            logger.info("  %-22s created", r.filename)
    for r in drift:
        if force and not check_only:
            logger.info("  %-22s overwritten", r.filename)
        else:
            logger.warning("  %-22s drift detected", r.filename)
            _print_diff(r)

    if wrote:
        logger.info("Wrote %d workflow file(s) to %s.", len(wrote), workflows_dir)

    drift_remaining = drift and not (force and not check_only)
    missing_remaining = missing and check_only

    if drift_remaining:
        logger.warning(
            "%d workflow(s) drifted from the generator output. "
            "Re-run with `generate-ci-gha --force` to overwrite.",
            len(drift),
        )
    if missing_remaining:
        logger.warning(
            "%d workflow(s) would be created. Re-run without `--check` to write.",
            len(missing),
        )

    if drift_remaining or missing_remaining:
        return 1
    return 0


__all__ = ["run", "State", "FileResult"]
