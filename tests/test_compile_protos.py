"""Tests for the `compile-protos` runner and toolchain probing."""

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.compile_protos import runner as runner_mod
from scitrera_repo_tools.compile_protos import tools
from scitrera_repo_tools.compile_protos.runner import State, run
from scitrera_repo_tools.compile_protos.tools import (
    ToolState,
    normalize_version,
    resolve_ts_package_dir,
)
from scitrera_repo_tools.version_sync.config import load_config

VERSIONS = '''\
my-pkg: 0.1.0

proto:
  dir: api/proto
  files: [thing.proto]
  toolchain:
    protoc: "31.1"
  outputs:
    python:
      path: pkg/proto
'''


@pytest.fixture
def repo(tmp_path: Path, write_file) -> Path:
    write_file(tmp_path / "versions.yaml", VERSIONS)
    write_file(tmp_path / "api/proto/thing.proto", 'syntax = "proto3";\n')
    return tmp_path


def _config(repo: Path):
    return load_config(repo / "versions.yaml")


def _fake_generation(files: dict):
    """Return a generate_into stub that writes `files` into the mirror root."""
    def _gen(config, dest_root: Path, python_exe, languages):
        for rel, content in files.items():
            path = dest_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return _gen


# ── version parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("31.1", "31.1"),
    ("v1.36.11", "1.36.11"),
    ("  v1.6.2  ", "1.6.2"),
    (None, None),
])
def test_normalize_version(raw, expected):
    assert normalize_version(raw) == expected


@pytest.mark.parametrize("output,expected", [
    ("libprotoc 31.1", "31.1"),
    ("libprotoc 3.21.12", "3.21.12"),
    ("protoc-gen-go v1.36.11", "1.36.11"),
    ("protoc-gen-go-grpc 1.6.2", "1.6.2"),
    ("0.8.1", "0.8.1"),
    ("\n\nlibprotoc 31.1\n", "31.1"),
    ("", None),
    (None, None),
    # Error text must never be mistaken for a version. Seen in the wild when
    # node is off PATH: the last token of the error is the word "directory".
    ("/usr/bin/env: 'node': No such file or directory", None),
    ("command not found", None),
    ("Traceback (most recent call last):", None),
])
def test_parse_version_output(output, expected):
    assert tools._parse_version_output(output) == expected


def test_failed_probe_reports_missing_not_a_bogus_version():
    """A non-zero --version must yield None, not its stderr text."""
    assert tools._run(["false"]) is None
    # A command that does not exist at all.
    assert tools._run(["definitely-not-a-real-binary-xyz"]) is None


def test_prerelease_versions_still_parse():
    assert tools._parse_version_output("protoc-gen-go v1.36.11-rc1") == "1.36.11-rc1"


def test_compare_states():
    ok = tools._compare("protoc", "protoc", "31.1", "31.1", "hint")
    assert ok.state is ToolState.OK and not ok.is_error

    # A `v` prefix on either side must not read as a mismatch.
    vok = tools._compare("p", "p", "v1.6.2", "1.6.2", "hint")
    assert vok.state is ToolState.OK

    mismatch = tools._compare("protoc", "protoc", "31.1", "3.21.12", "hint")
    assert mismatch.state is ToolState.MISMATCH and mismatch.is_error
    assert "hint" in mismatch.describe()

    missing = tools._compare("protoc", "protoc", "31.1", None, "install it")
    assert missing.state is ToolState.MISSING and missing.is_error

    unpinned = tools._compare("protoc", "protoc", None, "31.1", "hint")
    assert unpinned.state is ToolState.UNPINNED and not unpinned.is_error


def test_bundled_protoc_cross_check(monkeypatch):
    """grpc_tools' bundled protoc must agree with the standalone pin's major."""
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: "31.1")
    assert tools.check_bundled_protoc("31.1", "py").state is ToolState.OK

    # The exact inconsistency found in the wild: Go stamped 3.21.x, Python 31.x.
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: "31.1")
    bad = tools.check_bundled_protoc("3.21.12", "py")
    assert bad.state is ToolState.MISMATCH and bad.is_error

    # No pin, or an unprobeable interpreter, yields no opinion.
    assert tools.check_bundled_protoc(None, "py") is None
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: None)
    assert tools.check_bundled_protoc("31.1", "py") is None


def test_verify_toolchain_only_probes_needed_tools(repo, monkeypatch):
    """A python-only config must not demand Go or npm tooling."""
    monkeypatch.setattr(tools, "grpcio_tools_version", lambda _exe: "1.76.0")
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: "31.1")
    cfg = _config(repo)
    keys = {c.key for c in tools.verify_toolchain(cfg.root, cfg.proto, "py")}
    assert keys == {"grpcio_tools", "grpc_tools_protoc"}


ALL_LANGS = '''\
my-pkg: 0.1.0
proto:
  dir: api/proto
  files: [thing.proto]
  toolchain: {protoc: "33.5", protoc_gen_go: "v1.36.11", protoc_gen_go_grpc: "v1.6.2",
              grpcio_tools: "1.81.1", proto_loader: "0.8.1"}
  outputs:
    go: {path: api/proto}
    python: {path: pkg/proto}
    typescript: {path: ts/src/proto, package_dir: ts}
'''


def test_verify_toolchain_honors_language_selection(tmp_path, write_file, monkeypatch):
    """`--lang X` must not demand the other languages' toolchains.

    This is what lets the generated proto-check workflow run one job per
    language, each provisioning only its own tools.
    """
    monkeypatch.setattr(tools, "grpcio_tools_version", lambda _exe: "1.81.1")
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: "33.5")
    write_file(tmp_path / "versions.yaml", ALL_LANGS)
    cfg = load_config(tmp_path / "versions.yaml")

    def keys_for(langs):
        return {c.key for c in tools.verify_toolchain(cfg.root, cfg.proto, "py", languages=langs)}

    assert keys_for(["python"]) == {"grpcio_tools", "grpc_tools_protoc"}
    assert keys_for(["typescript"]) == {"proto_loader"}
    assert keys_for(["go"]) == {"protoc", "protoc_gen_go", "protoc_gen_go_grpc", "gofmt"}
    # Default (None) still means "everything configured".
    assert len(keys_for(None)) == 7


# ── python import rewriting ───────────────────────────────────────────────────

def test_fix_relative_imports(tmp_path, write_file):
    write_file(tmp_path / "a_pb2_grpc.py", (
        "import grpc\n"
        "import a_pb2 as a__pb2\n"
        "from google.protobuf import descriptor as _descriptor\n"
    ))
    write_file(tmp_path / "b_pb2.py", "import a_pb2\n")

    runner_mod._fix_relative_imports(tmp_path)

    grpc_text = (tmp_path / "a_pb2_grpc.py").read_text()
    assert "from . import a_pb2 as a__pb2" in grpc_text
    # Unrelated imports must be untouched.
    assert "import grpc\n" in grpc_text
    assert "from google.protobuf import descriptor as _descriptor" in grpc_text
    assert (tmp_path / "b_pb2.py").read_text() == "from . import a_pb2\n"


# ── TS package discovery ──────────────────────────────────────────────────────

def test_resolve_ts_package_dir_explicit(tmp_path, write_file):
    write_file(tmp_path / "versions.yaml", '''\
    my-pkg: 0.1.0
    proto:
      dir: api
      files: [a.proto]
      outputs:
        typescript: {path: sdk/ts/src/proto, package_dir: sdk/ts}
    ''')
    cfg = load_config(tmp_path / "versions.yaml")
    assert resolve_ts_package_dir(cfg.root, cfg.proto) == (tmp_path / "sdk/ts").resolve()


def test_resolve_ts_package_dir_discovered(tmp_path, write_file, write_json):
    write_file(tmp_path / "versions.yaml", '''\
    my-pkg: 0.1.0
    proto:
      dir: api
      files: [a.proto]
      outputs:
        typescript: {path: sdk/ts/src/proto}
    ''')
    write_json(tmp_path / "sdk/ts/package.json", {"name": "ts"})
    (tmp_path / "sdk/ts/src/proto").mkdir(parents=True)
    cfg = load_config(tmp_path / "versions.yaml")
    assert resolve_ts_package_dir(cfg.root, cfg.proto) == (tmp_path / "sdk/ts").resolve()


def test_resolve_ts_package_dir_absent(tmp_path, write_file):
    write_file(tmp_path / "versions.yaml", '''\
    my-pkg: 0.1.0
    proto:
      dir: api
      files: [a.proto]
      outputs:
        typescript: {path: sdk/ts/src/proto}
    ''')
    cfg = load_config(tmp_path / "versions.yaml")
    assert resolve_ts_package_dir(cfg.root, cfg.proto) is None


# ── classification ────────────────────────────────────────────────────────────

def test_classify_three_states(tmp_path):
    dest, real = tmp_path / "gen", tmp_path / "real"
    for base in (dest, real):
        (base / "pkg").mkdir(parents=True)
    (dest / "pkg/same.py").write_text("x\n")
    (real / "pkg/same.py").write_text("x\n")
    (dest / "pkg/changed.py").write_text("new\n")
    (real / "pkg/changed.py").write_text("old\n")
    (dest / "pkg/absent.py").write_text("new\n")

    by_rel = {r.rel: r.state for r in runner_mod._classify(dest, real)}
    assert by_rel == {
        "pkg/same.py": State.OK,
        "pkg/changed.py": State.DRIFT,
        "pkg/absent.py": State.MISSING,
    }


# ── run(): check mode ─────────────────────────────────────────────────────────

def test_check_flags_untracked_missing_file(repo, monkeypatch, capsys):
    """The git-diff blind spot: a generated file never committed is MISSING.

    `git diff --name-only` cannot see an untracked file, so the old shell check
    passed while generated code was absent from the commit entirely.
    """
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "generated\n"}))
    rc = run(_config(repo), check_only=True, skip_verify=True)
    assert rc == 1
    assert not (repo / "pkg/proto/thing_pb2.py").exists()


def test_check_reports_drift_with_diff(repo, monkeypatch, capsys):
    (repo / "pkg/proto").mkdir(parents=True)
    (repo / "pkg/proto/thing_pb2.py").write_text("stale\n")
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "fresh\n"}))
    rc = run(_config(repo), check_only=True, skip_verify=True)
    assert rc == 1
    out = capsys.readouterr().out
    assert "-stale" in out and "+fresh" in out
    # check mode never writes
    assert (repo / "pkg/proto/thing_pb2.py").read_text() == "stale\n"


def test_check_clean_returns_zero(repo, monkeypatch):
    (repo / "pkg/proto").mkdir(parents=True)
    (repo / "pkg/proto/thing_pb2.py").write_text("same\n")
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "same\n"}))
    assert run(_config(repo), check_only=True, skip_verify=True) == 0


def test_no_diff_suppresses_output(repo, monkeypatch, capsys):
    (repo / "pkg/proto").mkdir(parents=True)
    (repo / "pkg/proto/thing_pb2.py").write_text("stale\n")
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "fresh\n"}))
    run(_config(repo), check_only=True, skip_verify=True, show_diff=False)
    assert "-stale" not in capsys.readouterr().out


# ── run(): apply mode ─────────────────────────────────────────────────────────

def test_apply_creates_and_updates(repo, monkeypatch):
    (repo / "pkg/proto").mkdir(parents=True)
    (repo / "pkg/proto/thing_pb2.py").write_text("stale\n")
    monkeypatch.setattr(runner_mod, "generate_into", _fake_generation({
        "pkg/proto/thing_pb2.py": "fresh\n",
        "pkg/proto/thing_pb2_grpc.py": "brand new\n",
    }))
    assert run(_config(repo), check_only=False, skip_verify=True) == 0
    assert (repo / "pkg/proto/thing_pb2.py").read_text() == "fresh\n"
    assert (repo / "pkg/proto/thing_pb2_grpc.py").read_text() == "brand new\n"


def test_apply_leaves_unrelated_files_alone(repo, monkeypatch):
    (repo / "pkg/proto").mkdir(parents=True)
    (repo / "pkg/proto/handwritten.py").write_text("mine\n")
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "gen\n"}))
    run(_config(repo), check_only=False, skip_verify=True)
    assert (repo / "pkg/proto/handwritten.py").read_text() == "mine\n"


def test_apply_is_idempotent(repo, monkeypatch):
    monkeypatch.setattr(runner_mod, "generate_into",
                        _fake_generation({"pkg/proto/thing_pb2.py": "gen\n"}))
    cfg = _config(repo)
    assert run(cfg, check_only=False, skip_verify=True) == 0
    assert run(cfg, check_only=False, skip_verify=True) == 0
    assert run(cfg, check_only=True, skip_verify=True) == 0


# ── run(): guard rails ────────────────────────────────────────────────────────

def test_missing_proto_block_exits_two(tmp_path, write_file):
    write_file(tmp_path / "versions.yaml", "my-pkg: 0.1.0\n")
    assert run(load_config(tmp_path / "versions.yaml"), check_only=True) == 2


def test_unconfigured_language_exits_two(repo):
    assert run(_config(repo), check_only=True, languages=["go"], skip_verify=True) == 2


def test_empty_generation_exits_two(repo, monkeypatch):
    monkeypatch.setattr(runner_mod, "generate_into", _fake_generation({}))
    assert run(_config(repo), check_only=True, skip_verify=True) == 2


def test_generation_error_exits_two_without_touching_tree(repo, monkeypatch):
    def _boom(config, dest_root, python_exe, languages):
        raise runner_mod.GenerationError("protoc exploded")
    monkeypatch.setattr(runner_mod, "generate_into", _boom)
    assert run(_config(repo), check_only=False, skip_verify=True) == 2
    assert not (repo / "pkg/proto").exists()


def test_toolchain_failure_blocks_generation(repo, monkeypatch):
    """Verification runs before codegen, so nothing is written on a bad pin."""
    called = []
    monkeypatch.setattr(runner_mod, "generate_into",
                        lambda *a, **k: called.append(1))
    monkeypatch.setattr(tools, "grpcio_tools_version", lambda _exe: "1.60.0")
    monkeypatch.setattr(tools, "bundled_protoc_version", lambda _exe: "31.1")
    write = repo / "versions.yaml"
    write.write_text(write.read_text().replace(
        '    protoc: "31.1"', '    protoc: "31.1"\n    grpcio_tools: "1.76.0"'
    ), encoding="utf-8")
    assert run(_config(repo), check_only=True) == 2
    assert not called


def test_missing_proto_file_is_reported(repo, monkeypatch):
    """generate_into validates inputs before invoking any compiler."""
    (repo / "api/proto/thing.proto").unlink()
    cfg = _config(repo)
    with pytest.raises(runner_mod.GenerationError, match="proto.files not found"):
        runner_mod.generate_into(cfg, repo / "out", "py", ("python",))


def test_missing_proto_dir_is_reported(tmp_path, write_file):
    write_file(tmp_path / "versions.yaml", VERSIONS)
    cfg = load_config(tmp_path / "versions.yaml")
    with pytest.raises(runner_mod.GenerationError, match="proto.dir does not exist"):
        runner_mod.generate_into(cfg, tmp_path / "out", "py", ("python",))


def test_unimplemented_ts_generator_reports_clearly(tmp_path, write_file, write_json):
    write_file(tmp_path / "versions.yaml", '''\
    my-pkg: 0.1.0
    proto:
      dir: api
      files: [a.proto]
      outputs:
        typescript: {path: ts/src/proto, generator: ts-proto, package_dir: ts}
    ''')
    write_file(tmp_path / "api/a.proto", 'syntax = "proto3";\n')
    write_json(tmp_path / "ts/package.json", {"name": "ts"})
    cfg = load_config(tmp_path / "versions.yaml")
    with pytest.raises(runner_mod.GenerationError, match="not implemented yet"):
        runner_mod.generate_into(cfg, tmp_path / "out", "py", ("typescript",))
