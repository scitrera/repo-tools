"""Runs `npm audit` (and optionally `npm audit fix`) across TS packages."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from ..version_sync.config import SyncConfig
from ..version_sync.discovery import manifests_for_language

logger = logging.getLogger("scitrera_repo_tools.npm_audit")

AUDIT_LEVELS = ("info", "low", "moderate", "high", "critical")

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BOLD = "\033[1m"
NC = "\033[0m"


@dataclass
class AuditResult:
    failures: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _color(text: str, code: str, *, use_color: bool) -> str:
    return f"{code}{text}{NC}" if use_color else text


def _run_step(
    label: str,
    cmd: Sequence[str],
    *,
    cwd: Path,
    result: AuditResult,
    use_color: bool,
    runner: Callable[..., "subprocess.CompletedProcess[str]"],
) -> None:
    """Run one npm step, color-code the outcome, append to failures on non-zero exit."""
    print(_color(f"  → {label}", BOLD, use_color=use_color))
    proc = runner(list(cmd), cwd=str(cwd), check=False)
    if proc.returncode == 0:
        print("    " + _color("✓ clean", GREEN, use_color=use_color))
    else:
        print("    " + _color("✗ issues", RED, use_color=use_color))
        result.failures.append(label)


def _ensure_installed(
    pkg_dir: Path,
    project: str,
    *,
    result: AuditResult,
    use_color: bool,
    runner: Callable[..., "subprocess.CompletedProcess[str]"],
) -> bool:
    """Bail on missing lockfile, prime node_modules via `npm ci`."""
    if not (pkg_dir / "package-lock.json").is_file():
        print(_color(
            f"  {project} has no package-lock.json — skipping audit",
            RED, use_color=use_color,
        ))
        result.failures.append(f"{project}: missing lockfile")
        return False
    if not (pkg_dir / "node_modules").is_dir():
        print(_color(
            f"  ↻ priming node_modules in {project} (npm ci)",
            YELLOW, use_color=use_color,
        ))
        proc = runner(
            ["npm", "ci", "--no-audit", "--no-fund", "--silent"],
            cwd=str(pkg_dir),
            check=False,
        )
        if proc.returncode != 0:
            print(_color(
                f"  npm ci failed in {project}",
                RED, use_color=use_color,
            ))
            result.failures.append(f"{project}: npm ci failed")
            return False
    return True


def run(
    config: SyncConfig,
    *,
    selected: Optional[Sequence[str]],
    fix: bool,
    force: bool,
    level: Optional[str],
    use_color: Optional[bool] = None,
    runner: Optional[Callable[..., "subprocess.CompletedProcess[str]"]] = None,
) -> int:
    """Drive `npm audit` over the typescript projects from versions.yaml.

    - `selected=None` → audit every typescript project, sorted.
    - `selected=[...]` → audit only those project names (must exist in versions.yaml).
    - `runner` defaults to `subprocess.run`; tests inject a fake.
    """
    if runner is None:
        runner = subprocess.run
    if use_color is None:
        use_color = sys.stdout.isatty()

    manifests = manifests_for_language(config, "typescript")
    if not manifests:
        logger.warning(
            "No typescript projects found in versions.yaml (no `type: package` rules)."
        )
        return 0

    if selected:
        unknown = [s for s in selected if s not in manifests]
        if unknown:
            available = ", ".join(sorted(manifests))
            print(_color(
                f"Unknown project(s): {', '.join(unknown)}",
                RED, use_color=use_color,
            ), file=sys.stderr)
            print(f"Available typescript projects: {available}", file=sys.stderr)
            return 1
        targets = list(selected)
    else:
        targets = sorted(manifests)

    if force and not fix:
        print(_color(
            "--force has no effect without --fix; ignoring.",
            YELLOW, use_color=use_color,
        ))

    level_args: List[str] = ["--audit-level", level] if level else []
    result = AuditResult()

    for project in targets:
        package_json = manifests[project]
        pkg_dir = package_json.parent
        print()
        print(_color(f"━━━ npm-audit: {project} ━━━", YELLOW, use_color=use_color))

        if not pkg_dir.is_dir():
            print(_color(
                f"  package directory missing: {pkg_dir}",
                RED, use_color=use_color,
            ))
            result.failures.append(f"{project}: missing directory")
            continue

        if not _ensure_installed(
            pkg_dir, project,
            result=result, use_color=use_color, runner=runner,
        ):
            continue

        if fix:
            if force:
                _run_step(
                    f"{project}: audit fix --force",
                    ["npm", "audit", "fix", "--force", *level_args],
                    cwd=pkg_dir, result=result,
                    use_color=use_color, runner=runner,
                )
            else:
                _run_step(
                    f"{project}: audit fix",
                    ["npm", "audit", "fix", *level_args],
                    cwd=pkg_dir, result=result,
                    use_color=use_color, runner=runner,
                )

        _run_step(
            f"{project}: audit",
            ["npm", "audit", *level_args],
            cwd=pkg_dir, result=result,
            use_color=use_color, runner=runner,
        )

    print()
    if result.ok:
        print(_color("No outstanding vulnerabilities.", GREEN + BOLD, use_color=use_color))
        return 0
    print(_color(
        f"{len(result.failures)} audit step(s) reported issues:",
        RED + BOLD, use_color=use_color,
    ))
    for f in result.failures:
        print(_color(f"  ✗ {f}", RED, use_color=use_color))
    return 1


__all__ = ["run", "AuditResult", "AUDIT_LEVELS"]
