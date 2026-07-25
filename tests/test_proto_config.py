"""Schema tests for the `proto:` block."""

from __future__ import annotations

from pathlib import Path

import pytest

from scitrera_repo_tools.version_sync.config import ConfigError, load_config

FULL = '''\
my-pkg: 0.1.0

preferred_versions:
  go:
    "google.golang.org/protobuf": "1.36.11"

proto:
  dir: api/proto
  files: [aether.proto, sandbox_relay_tunnel.proto]
  toolchain:
    protoc: "31.1"
    protoc_gen_go_grpc: "v1.6.2"
    grpcio_tools: "1.76.0"
    proto_loader: "0.8.1"
  outputs:
    go:
      path: api/proto
    python:
      path: sdk/python-client/pkg/proto
    typescript:
      path: sdk/typescript/src/proto
      package_dir: sdk/typescript
'''


def _load(tmp_path: Path, write_file, body: str):
    write_file(tmp_path / "versions.yaml", body)
    return load_config(tmp_path / "versions.yaml")


def test_full_block_parses(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, FULL)
    proto = cfg.proto
    assert not proto.is_empty
    assert proto.dir == "api/proto"
    assert proto.files == ("aether.proto", "sandbox_relay_tunnel.proto")
    assert proto.languages == ("go", "python", "typescript")
    assert proto.go.path == "api/proto"
    assert proto.go.paths == "source_relative"
    assert proto.python.stubs is True
    assert proto.typescript.generator == "proto-loader"
    assert proto.typescript.package_dir == "sdk/typescript"


def test_absent_block_is_empty(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, "my-pkg: 0.1.0\n")
    assert cfg.proto.is_empty
    assert cfg.proto.languages == ()


def test_proto_is_reserved_not_a_project_version(tmp_path, write_file):
    """`proto` must not be mistaken for a project version entry."""
    cfg = _load(tmp_path, write_file, FULL)
    assert "proto" not in cfg.project_versions


def test_protoc_gen_go_derived_from_go_module_pin(tmp_path, write_file):
    """Omitted pin derives from preferred_versions.go, v-normalized."""
    cfg = _load(tmp_path, write_file, FULL)
    assert cfg.proto.toolchain.protoc_gen_go == "v1.36.11"


def test_explicit_null_also_derives(tmp_path, write_file):
    body = FULL.replace('    protoc: "31.1"', '    protoc: "31.1"\n    protoc_gen_go: null')
    cfg = _load(tmp_path, write_file, body)
    assert cfg.proto.toolchain.protoc_gen_go == "v1.36.11"


def test_explicit_pin_overrides_derivation(tmp_path, write_file):
    body = FULL.replace('    protoc: "31.1"', '    protoc: "31.1"\n    protoc_gen_go: "1.30.0"')
    cfg = _load(tmp_path, write_file, body)
    assert cfg.proto.toolchain.protoc_gen_go == "v1.30.0"


def test_derivation_absent_when_no_go_pin(tmp_path, write_file):
    body = FULL.replace('  go:\n    "google.golang.org/protobuf": "1.36.11"\n', '  go: {}\n')
    cfg = _load(tmp_path, write_file, body)
    assert cfg.proto.toolchain.protoc_gen_go is None


def test_go_module_pins_are_v_normalized(tmp_path, write_file):
    body = FULL.replace('protoc_gen_go_grpc: "v1.6.2"', 'protoc_gen_go_grpc: "1.6.2"')
    cfg = _load(tmp_path, write_file, body)
    assert cfg.proto.toolchain.protoc_gen_go_grpc == "v1.6.2"


def test_non_go_pins_are_not_v_prefixed(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, FULL)
    assert cfg.proto.toolchain.protoc == "31.1"
    assert cfg.proto.toolchain.grpcio_tools == "1.76.0"


@pytest.mark.parametrize("body,message", [
    ("proto:\n  files: [a.proto]\n  outputs:\n    go: {path: x}\n", "proto.dir"),
    ("proto:\n  dir: api\n  outputs:\n    go: {path: x}\n", "proto.files"),
    ("proto:\n  dir: api\n  files: []\n  outputs:\n    go: {path: x}\n", "proto.files"),
    ("proto:\n  dir: api\n  files: [a.txt]\n  outputs:\n    go: {path: x}\n", "'.proto'"),
    ("proto:\n  dir: api\n  files: [a.proto, a.proto]\n  outputs:\n    go: {path: x}\n", "duplicate"),
    ("proto:\n  dir: api\n  files: [a.proto]\n", "proto.outputs"),
    ("proto:\n  dir: api\n  files: [a.proto]\n  outputs: {}\n", "proto.outputs"),
    ("proto:\n  dir: api\n  files: [a.proto]\n  outputs:\n    go: {}\n", "proto.outputs.go.path"),
])
def test_invalid_blocks_rejected(tmp_path, write_file, body, message):
    with pytest.raises(ConfigError) as exc:
        _load(tmp_path, write_file, body)
    assert message in str(exc.value)


def test_unknown_keys_rejected_at_every_level(tmp_path, write_file):
    """Typos must fail loudly — a silently-ignored pin is the bug being fixed."""
    cases = [
        ("proto:\n  dir: api\n  files: [a.proto]\n  protoc: '31.1'\n"
         "  outputs:\n    go: {path: x}\n", "proto:"),
        ("proto:\n  dir: api\n  files: [a.proto]\n  toolchain: {protoc_version: '31'}\n"
         "  outputs:\n    go: {path: x}\n", "proto.toolchain:"),
        ("proto:\n  dir: api\n  files: [a.proto]\n  outputs:\n    golang: {path: x}\n",
         "proto.outputs:"),
        ("proto:\n  dir: api\n  files: [a.proto]\n  outputs:\n    go: {path: x, fmt: true}\n",
         "proto.outputs.go:"),
    ]
    for body, where in cases:
        with pytest.raises(ConfigError) as exc:
            _load(tmp_path, write_file, body)
        assert "unknown key" in str(exc.value)
        assert where.rstrip(":") in str(exc.value)


def test_ts_generator_enum_accepts_all_three(tmp_path, write_file):
    """Schema models the extension point even though only one is wired up."""
    for gen in ("proto-loader", "ts-proto", "protoc-gen-ts"):
        body = (
            f"proto:\n  dir: api\n  files: [a.proto]\n"
            f"  outputs:\n    typescript: {{path: out, generator: {gen}}}\n"
        )
        cfg = _load(tmp_path, write_file, body)
        assert cfg.proto.typescript.generator == gen


def test_ts_generator_rejects_unknown(tmp_path, write_file):
    body = ("proto:\n  dir: api\n  files: [a.proto]\n"
            "  outputs:\n    typescript: {path: out, generator: nanopb}\n")
    with pytest.raises(ConfigError, match="generator"):
        _load(tmp_path, write_file, body)


def test_go_paths_mode_validated(tmp_path, write_file):
    body = ("proto:\n  dir: api\n  files: [a.proto]\n"
            "  outputs:\n    go: {path: out, paths: sideways}\n")
    with pytest.raises(ConfigError, match="proto.outputs.go.paths"):
        _load(tmp_path, write_file, body)


def test_boolean_fields_reject_non_booleans(tmp_path, write_file):
    body = ("proto:\n  dir: api\n  files: [a.proto]\n"
            "  outputs:\n    go: {path: out, gofmt: 'yes'}\n")
    with pytest.raises(ConfigError, match="expected boolean"):
        _load(tmp_path, write_file, body)


def test_ts_options_default_and_override(tmp_path, write_file):
    cfg = _load(tmp_path, write_file, FULL)
    assert "--oneofs" in cfg.proto.typescript.options

    body = ("proto:\n  dir: api\n  files: [a.proto]\n"
            "  outputs:\n    typescript: {path: out, options: ['--longs=Number']}\n")
    cfg2 = _load(tmp_path, write_file, body)
    assert cfg2.proto.typescript.options == ("--longs=Number",)


def test_single_language_only(tmp_path, write_file):
    body = "proto:\n  dir: api\n  files: [a.proto]\n  outputs:\n    go: {path: out}\n"
    cfg = _load(tmp_path, write_file, body)
    assert cfg.proto.languages == ("go",)
    assert cfg.proto.python is None
    assert cfg.proto.typescript is None
