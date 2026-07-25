"""Proto codegen orchestration for `compile-protos`.

Generation always happens into a temporary mirror of the repo layout first,
never straight into the working tree. That single choice buys three things:

- `--check` and apply share one code path, so the drift check cannot disagree
  with what apply would produce;
- post-processing (gofmt, import rewrites) runs only on freshly generated
  files, so it can never reformat unrelated checked-in sources;
- a codegen failure leaves the working tree untouched.

The comparison enumerates the *generated* file set, which is what makes this a
strict improvement over `git diff --name-only`: a generated file that was never
committed is untracked and therefore invisible to git, but shows up here as
MISSING.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import difflib
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..version_sync.config import ProtoConfig, SyncConfig
from .tools import ToolCheck, ToolState, ts_generator_binary, verify_toolchain

logger = logging.getLogger("scitrera_repo_tools.compile_protos")

_CODEGEN_TIMEOUT = 300

# Bare sibling imports emitted by protoc's Python backend, which break as soon
# as the generated modules live inside a package.
_BARE_IMPORT_AS = re.compile(r"^import (\w+_pb2) as (\w+)$", re.MULTILINE)
_BARE_IMPORT = re.compile(r"^import (\w+_pb2)$", re.MULTILINE)


class State(str, Enum):
    OK = "ok"            # on-disk file matches freshly generated output
    MISSING = "missing"  # generated but absent on disk (git-invisible when untracked)
    DRIFT = "drift"      # on-disk file differs


@dataclass(frozen=True)
class FileResult:
    rel: str
    state: State
    generated: Path
    target: Path


class GenerationError(RuntimeError):
    """A codegen invocation failed; message carries the tool's own output."""


def _run_codegen(cmd: Sequence[str], cwd: Path, what: str) -> None:
    try:
        proc = subprocess.run(
            list(cmd), cwd=str(cwd), capture_output=True, text=True,
            timeout=_CODEGEN_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GenerationError(f"{what}: executable not found ({cmd[0]})") from exc
    except subprocess.SubprocessError as exc:
        raise GenerationError(f"{what}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GenerationError(f"{what} failed (exit {proc.returncode}):\n{detail}")


def _generate_go(proto: ProtoConfig, proto_dir: Path, dest_root: Path) -> None:
    go = proto.go
    out = (dest_root / go.path).resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmd: List[str] = [
        "protoc", "-I.",
        f"--go_out={out}", f"--go_opt=paths={go.paths}",
    ]
    if go.grpc:
        cmd += [f"--go-grpc_out={out}", f"--go-grpc_opt=paths={go.paths}"]
    cmd += list(proto.files)
    _run_codegen(cmd, proto_dir, "protoc (go)")

    if go.gofmt:
        # Scoped to the temp tree, so checked-in Go outside the generated set is
        # never touched.
        _run_codegen(["gofmt", "-w", str(out)], proto_dir, "gofmt")


def _fix_relative_imports(directory: Path) -> None:
    for path in sorted(directory.rglob("*.py")):
        original = path.read_text(encoding="utf-8")
        patched = _BARE_IMPORT_AS.sub(r"from . import \1 as \2", original)
        patched = _BARE_IMPORT.sub(r"from . import \1", patched)
        if patched != original:
            path.write_text(patched, encoding="utf-8")


def _generate_python(proto: ProtoConfig, proto_dir: Path, dest_root: Path,
                     python_exe: str, real_root: Path) -> None:
    py = proto.python
    out = (dest_root / py.path).resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmd = [python_exe, "-m", "grpc_tools.protoc", "-I.", f"--python_out={out}"]
    if py.stubs:
        cmd.append(f"--pyi_out={out}")
    if py.grpc:
        cmd.append(f"--grpc_python_out={out}")
    cmd += list(proto.files)
    _run_codegen(cmd, proto_dir, "grpc_tools.protoc (python)")

    if py.fix_relative_imports:
        _fix_relative_imports(out)

    if py.ensure_init_py:
        # Only materialize __init__.py when the real tree lacks one. Emitting an
        # empty file unconditionally would report drift against — and on apply
        # clobber — a package initializer that already has content.
        real_init = (real_root / py.path / "__init__.py")
        if not real_init.exists():
            (out / "__init__.py").touch()


def _generate_typescript(proto: ProtoConfig, proto_dir: Path, dest_root: Path,
                         real_root: Path) -> None:
    ts = proto.typescript
    if ts.generator != "proto-loader":
        raise GenerationError(
            f"proto.outputs.typescript.generator='{ts.generator}' is not "
            "implemented yet; currently supported: proto-loader"
        )
    binary = ts_generator_binary(real_root, proto)
    if binary is None:
        raise GenerationError(
            "proto-loader-gen-types not found; run `npm install` in the "
            "TypeScript package (or set proto.outputs.typescript.package_dir)"
        )
    out = (dest_root / ts.path).resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmd = [str(binary), *ts.options, f"--grpcLib={ts.grpc_lib}", f"--outDir={out}"]
    cmd += list(proto.files)
    _run_codegen(cmd, proto_dir, "proto-loader-gen-types (typescript)")


def generate_into(config: SyncConfig, dest_root: Path, python_exe: str,
                  languages: Sequence[str]) -> None:
    """Generate every enabled language output beneath `dest_root`.

    Output paths mirror their real relative locations so comparison and apply
    are simple path joins.
    """
    proto = config.proto
    proto_dir = (config.root / proto.dir).resolve()
    if not proto_dir.is_dir():
        raise GenerationError(f"proto.dir does not exist: {proto_dir}")
    missing = [f for f in proto.files if not (proto_dir / f).is_file()]
    if missing:
        raise GenerationError(f"proto.files not found in {proto_dir}: {missing}")

    if "go" in languages and proto.go is not None:
        _generate_go(proto, proto_dir, dest_root)
    if "python" in languages and proto.python is not None:
        _generate_python(proto, proto_dir, dest_root, python_exe, config.root)
    if "typescript" in languages and proto.typescript is not None:
        _generate_typescript(proto, proto_dir, dest_root, config.root)


def _classify(dest_root: Path, real_root: Path) -> List[FileResult]:
    results: List[FileResult] = []
    for generated in sorted(p for p in dest_root.rglob("*") if p.is_file()):
        rel = generated.relative_to(dest_root)
        target = real_root / rel
        rel_str = str(rel).replace("\\", "/")
        if not target.exists():
            results.append(FileResult(rel_str, State.MISSING, generated, target))
        elif target.read_bytes() == generated.read_bytes():
            results.append(FileResult(rel_str, State.OK, generated, target))
        else:
            results.append(FileResult(rel_str, State.DRIFT, generated, target))
    return results


def _print_diff(result: FileResult) -> None:
    try:
        existing = result.target.read_text(encoding="utf-8").splitlines(keepends=True)
        desired = result.generated.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        logger.warning("    (binary file; diff suppressed)")
        return
    sys.stdout.write("".join(difflib.unified_diff(
        existing, desired,
        fromfile=f"a/{result.rel}", tofile=f"b/{result.rel}", n=3,
    )))


def _report_toolchain(checks: Sequence[ToolCheck], verbose: bool) -> List[ToolCheck]:
    errors = [c for c in checks if c.is_error]
    for check in checks:
        if check.is_error:
            logger.error("  %s", check.describe())
        elif check.state is ToolState.OK:
            if verbose:
                logger.info("  %s", check.describe())
        else:
            logger.warning("  %s", check.describe())
    return errors


def run(
    config: SyncConfig,
    *,
    check_only: bool,
    python_exe: Optional[str] = None,
    languages: Optional[Sequence[str]] = None,
    skip_verify: bool = False,
    show_diff: bool = True,
    verbose: bool = False,
) -> int:
    """Execute compile-protos. Returns a process exit code."""
    proto = config.proto
    if proto.is_empty:
        logger.error(
            "No `proto:` block in %s. Add one to use compile-protos.",
            config.yaml_path,
        )
        return 2

    python_exe = python_exe or sys.executable
    enabled = proto.languages
    selected: Tuple[str, ...] = tuple(languages) if languages else enabled
    unknown = [lang for lang in selected if lang not in enabled]
    if unknown:
        logger.error(
            "Requested language(s) %s have no proto.outputs entry; configured: %s",
            unknown, list(enabled) or "(none)",
        )
        return 2

    if not skip_verify:
        logger.info("Verifying proto toolchain against proto.toolchain pins...")
        checks = verify_toolchain(config.root, proto, python_exe)
        errors = _report_toolchain(checks, verbose)
        if errors:
            logger.error(
                "%d toolchain problem(s); refusing to generate. Fix the above, or "
                "pass --skip-verify to bypass (drifted artifacts are likely).",
                len(errors),
            )
            return 2

    with tempfile.TemporaryDirectory(prefix="repo-tools-protos-") as tmp:
        dest_root = Path(tmp)
        try:
            generate_into(config, dest_root, python_exe, selected)
        except GenerationError as exc:
            logger.error("%s", exc)
            return 2

        results = _classify(dest_root, config.root)
        if not results:
            logger.error("Codegen produced no files; nothing to compare or write.")
            return 2

        ok = [r for r in results if r.state is State.OK]
        missing = [r for r in results if r.state is State.MISSING]
        drift = [r for r in results if r.state is State.DRIFT]

        if check_only:
            for r in ok:
                if verbose:
                    logger.info("  %-58s in sync", r.rel)
            for r in missing:
                logger.warning("  %-58s missing", r.rel)
            for r in drift:
                logger.warning("  %-58s out of date", r.rel)
                if show_diff:
                    _print_diff(r)
            if missing or drift:
                logger.error(
                    "Proto-generated code is out of date (%d missing, %d changed) "
                    "across %d file(s). Run `compile-protos` and commit.",
                    len(missing), len(drift), len(results),
                )
                return 1
            logger.info("All %d generated file(s) are up to date.", len(results))
            return 0

        for r in missing + drift:
            r.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(r.generated, r.target)
        for r in ok:
            if verbose:
                logger.info("  %-58s unchanged", r.rel)
        for r in missing:
            logger.info("  %-58s created", r.rel)
        for r in drift:
            logger.info("  %-58s updated", r.rel)

        if missing or drift:
            logger.info(
                "Wrote %d file(s) (%d new, %d updated).",
                len(missing) + len(drift), len(missing), len(drift),
            )
        else:
            logger.info("All %d generated file(s) already up to date.", len(results))
        return 0


__all__ = ["run", "State", "FileResult", "GenerationError", "generate_into"]
