"""Toolchain discovery and pin verification for `compile-protos`.

Every binary that participates in proto codegen is probed for its version and
compared against the pin in `proto.toolchain`. This is the load-bearing part of
the subcommand: generated protobuf artifacts embed the versions of the tools
that produced them, so an unpinned or drifting compiler turns any byte-equality
check into a coin flip. Failing here — before generating anything — converts a
confusing CI diff into a precise local error.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

from ..version_sync.config import ProtoConfig

_PROBE_TIMEOUT = 30

# A version token: optional `v`, then digits/dots, with an optional pre-release
# or build suffix. Used to reject error text that merely looks like a word.
_VERSION_TOKEN = re.compile(r"^v?\d+(\.\d+)*([-+.][0-9A-Za-z.+-]*)?$")


class ToolState(str, Enum):
    OK = "ok"                # installed and matches the pin
    MISSING = "missing"      # binary/module not found
    MISMATCH = "mismatch"    # installed but wrong version
    UNPINNED = "unpinned"    # installed, no pin to check against
    UNKNOWN = "unknown"      # installed but version could not be parsed


@dataclass(frozen=True)
class ToolCheck:
    key: str                      # proto.toolchain key, e.g. "protoc"
    label: str                    # what was probed, e.g. "protoc"
    state: ToolState
    expected: Optional[str] = None
    found: Optional[str] = None
    hint: str = ""

    @property
    def is_error(self) -> bool:
        return self.state in (ToolState.MISSING, ToolState.MISMATCH)

    def describe(self) -> str:
        if self.state is ToolState.OK:
            return f"{self.label} {self.found} (pinned {self.expected})"
        if self.state is ToolState.UNPINNED:
            return f"{self.label} {self.found} (no pin in proto.toolchain)"
        if self.state is ToolState.UNKNOWN:
            return f"{self.label}: installed but version output unrecognized"
        if self.state is ToolState.MISSING:
            return f"{self.label}: not found — {self.hint}"
        return (
            f"{self.label}: found {self.found}, pinned {self.expected} — {self.hint}"
        )


def normalize_version(raw: Optional[str]) -> Optional[str]:
    """Strip whitespace and a single leading `v` for comparison purposes."""
    if raw is None:
        return None
    text = raw.strip()
    if text[:1] == "v":
        text = text[1:]
    return text


def _run(cmd: Sequence[str], cwd: Optional[Path] = None) -> Optional[str]:
    """Return combined output of `cmd`, or None when it cannot be executed."""
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        # A tool whose --version fails is not usable, and its error text must not
        # be mistaken for output: `/usr/bin/env: 'node': No such file or directory`
        # would otherwise parse as the version "directory".
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def _parse_version_output(text: Optional[str]) -> Optional[str]:
    """Pull the version token out of a `--version` line.

    Every tool here prints `<name> <version>` on one line (`libprotoc 31.1`,
    `protoc-gen-go v1.36.11`, `protoc-gen-go-grpc 1.6.2`). Taking the last
    whitespace-separated token of the first non-empty line is more robust than
    per-tool regexes, since none of these names end in a version-like token.
    """
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        token = normalize_version(line.split()[-1])
        # Reject anything that isn't version-shaped rather than reporting a
        # confident-looking bogus version; the caller treats None as "missing".
        return token if token and _VERSION_TOKEN.match(token) else None
    return None


def _compare(key: str, label: str, expected: Optional[str], found: Optional[str],
             hint: str) -> ToolCheck:
    if found is None:
        return ToolCheck(key, label, ToolState.MISSING, expected, None, hint)
    if expected is None:
        return ToolCheck(key, label, ToolState.UNPINNED, None, found)
    if normalize_version(expected) == found:
        return ToolCheck(key, label, ToolState.OK, normalize_version(expected), found)
    return ToolCheck(key, label, ToolState.MISMATCH, normalize_version(expected),
                     found, hint)


def _go_install_hint(pkg: str, version: Optional[str]) -> str:
    ver = version or "<version>"
    return f"install with: go install {pkg}@{ver}"


def check_protoc(expected: Optional[str]) -> ToolCheck:
    found = _parse_version_output(_run(["protoc", "--version"]))
    return _compare(
        "protoc", "protoc", expected, found,
        "install protoc and put it on PATH (see "
        "https://github.com/protocolbuffers/protobuf/releases)",
    )


def check_protoc_gen_go(expected: Optional[str]) -> ToolCheck:
    found = _parse_version_output(_run(["protoc-gen-go", "--version"]))
    return _compare(
        "protoc_gen_go", "protoc-gen-go", expected, found,
        _go_install_hint("google.golang.org/protobuf/cmd/protoc-gen-go", expected),
    )


def check_protoc_gen_go_grpc(expected: Optional[str]) -> ToolCheck:
    found = _parse_version_output(_run(["protoc-gen-go-grpc", "--version"]))
    return _compare(
        "protoc_gen_go_grpc", "protoc-gen-go-grpc", expected, found,
        _go_install_hint(
            "google.golang.org/grpc/cmd/protoc-gen-go-grpc", expected
        ),
    )


def check_gofmt() -> ToolCheck:
    """gofmt has no pin; it ships with the Go toolchain and is presence-only."""
    if shutil.which("gofmt") is None:
        return ToolCheck(
            "gofmt", "gofmt", ToolState.MISSING,
            hint="gofmt ships with Go; install Go or set proto.outputs.go.gofmt=false",
        )
    return ToolCheck("gofmt", "gofmt", ToolState.UNPINNED, found="present")


def grpcio_tools_version(python_exe: str) -> Optional[str]:
    out = _run([
        python_exe, "-c",
        "import importlib.metadata as m; print(m.version('grpcio-tools'))",
    ])
    if out is None:
        return None
    text = out.strip().splitlines()
    if not text:
        return None
    candidate = text[0].strip()
    # A traceback (module absent) rather than a version.
    if not candidate or not candidate[0].isdigit():
        return None
    return normalize_version(candidate)


def check_grpcio_tools(expected: Optional[str], python_exe: str) -> ToolCheck:
    found = grpcio_tools_version(python_exe)
    return _compare(
        "grpcio_tools", "grpcio-tools", expected, found,
        f"install with: {python_exe} -m pip install "
        f"grpcio-tools=={expected or '<version>'}",
    )


def bundled_protoc_version(python_exe: str) -> Optional[str]:
    """Version of the libprotoc that `grpc_tools.protoc` carries internally."""
    return _parse_version_output(
        _run([python_exe, "-m", "grpc_tools.protoc", "--version"])
    )


def check_bundled_protoc(expected_protoc: Optional[str], python_exe: str) -> Optional[ToolCheck]:
    """Cross-check `grpc_tools`' bundled protoc against the standalone pin.

    These are two independent compilers driving two language outputs from the
    same .proto files. When their majors disagree the repo ends up with Go
    artifacts stamped by one compiler and Python artifacts stamped by another —
    internally inconsistent generated code that no single pin would catch.
    Compared on major only, since the bundled build is not independently
    selectable.
    """
    if expected_protoc is None:
        return None
    found = bundled_protoc_version(python_exe)
    if found is None:
        return None
    want_major = normalize_version(expected_protoc).split(".")[0]
    got_major = found.split(".")[0]
    if want_major == got_major:
        return ToolCheck(
            "grpc_tools_protoc", "grpc_tools bundled protoc", ToolState.OK,
            want_major, found,
        )
    return ToolCheck(
        "grpc_tools_protoc", "grpc_tools bundled protoc", ToolState.MISMATCH,
        want_major, found,
        "grpc_tools bundles its own protoc; pick a grpcio-tools release whose "
        f"bundled protoc major matches proto.toolchain.protoc ({expected_protoc}), "
        "or change that pin to agree",
    )


def resolve_ts_package_dir(root: Path, proto: ProtoConfig) -> Optional[Path]:
    """Locate the npm package root that owns the TS generator binary.

    Explicit `package_dir` wins; otherwise walk up from the output path to the
    nearest `package.json`, which is where `node_modules/.bin` will live.
    """
    ts = proto.typescript
    if ts is None:
        return None
    if ts.package_dir:
        return (root / ts.package_dir).resolve()
    current = (root / ts.path).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "package.json").is_file():
            return candidate
        if candidate == root:
            break
    return None


def ts_generator_binary(root: Path, proto: ProtoConfig) -> Optional[Path]:
    """Path to `proto-loader-gen-types` inside the package's node_modules."""
    pkg_dir = resolve_ts_package_dir(root, proto)
    if pkg_dir is None:
        return None
    candidate = pkg_dir / "node_modules" / ".bin" / "proto-loader-gen-types"
    return candidate if candidate.exists() else None


def check_proto_loader(expected: Optional[str], root: Path, proto: ProtoConfig) -> ToolCheck:
    binary = ts_generator_binary(root, proto)
    pkg_dir = resolve_ts_package_dir(root, proto)
    where = pkg_dir if pkg_dir is not None else root
    hint = (
        f"run `npm install` in {where} "
        f"(expected @grpc/proto-loader{'@' + expected if expected else ''})"
    )
    if binary is None:
        return ToolCheck(
            "proto_loader", "proto-loader-gen-types", ToolState.MISSING,
            expected, None, hint,
        )
    found = _parse_version_output(_run([str(binary), "--version"]))
    return _compare("proto_loader", "proto-loader-gen-types", expected, found, hint)


def verify_toolchain(
    root: Path,
    proto: ProtoConfig,
    python_exe: str,
    languages: Optional[Sequence[str]] = None,
) -> List[ToolCheck]:
    """Probe the tools required by `languages` (default: every enabled output).

    Only tools actually needed are checked, so a Go-only repo is never asked to
    have grpcio-tools installed. Honoring `languages` matters beyond that: it
    lets a caller that restricted generation with `--lang` run in an environment
    provisioned for only that language — which is exactly how the generated
    proto-check workflow splits into one job per language, each installing its
    own toolchain and nothing else.
    """
    tc = proto.toolchain
    selected = set(languages) if languages is not None else set(proto.languages)
    checks: List[ToolCheck] = []

    if proto.go is not None and "go" in selected:
        checks.append(check_protoc(tc.protoc))
        checks.append(check_protoc_gen_go(tc.protoc_gen_go))
        if proto.go.grpc:
            checks.append(check_protoc_gen_go_grpc(tc.protoc_gen_go_grpc))
        if proto.go.gofmt:
            checks.append(check_gofmt())

    if proto.python is not None and "python" in selected:
        checks.append(check_grpcio_tools(tc.grpcio_tools, python_exe))
        cross = check_bundled_protoc(tc.protoc, python_exe)
        if cross is not None:
            checks.append(cross)

    if proto.typescript is not None and "typescript" in selected:
        checks.append(check_proto_loader(tc.proto_loader, root, proto))

    return checks


__all__ = [
    "ToolState",
    "ToolCheck",
    "normalize_version",
    "verify_toolchain",
    "resolve_ts_package_dir",
    "ts_generator_binary",
    "grpcio_tools_version",
    "bundled_protoc_version",
]
