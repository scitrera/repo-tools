"""Tests for `directory-split`."""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

from pathlib import Path

from scitrera_repo_tools.directory_split import (
    WorkItem,
    _bin_pack,
    _collect_work_items,
    main,
)


def test_top_level_files_split_evenly(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    for i in range(4):
        (target / f"f{i}.bin").write_bytes(b"x" * 100)

    rc = main([str(target), "2"])
    assert rc == 0

    b1 = tmp_path / "data-1"
    b2 = tmp_path / "data-2"
    assert b1.is_dir() and b2.is_dir()
    assert sum(1 for _ in b1.iterdir()) == 2
    assert sum(1 for _ in b2.iterdir()) == 2
    assert list(target.iterdir()) == []


def test_deep_split_distributes_children(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "big").mkdir()
    for i in range(4):
        (target / "big" / f"c{i}.bin").write_bytes(b"x" * 100)

    rc = main([str(target), "2"])
    assert rc == 0

    b1 = tmp_path / "data-1"
    b2 = tmp_path / "data-2"
    assert (b1 / "big").is_dir()
    assert (b2 / "big").is_dir()
    assert sum(1 for _ in (b1 / "big").iterdir()) == 2
    assert sum(1 for _ in (b2 / "big").iterdir()) == 2
    assert not (target / "big").exists()


def test_empty_directory_preserved(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "empty_dir").mkdir()
    (target / "f.bin").write_bytes(b"x" * 10)

    rc = main([str(target), "2"])
    assert rc == 0

    b1 = tmp_path / "data-1"
    b2 = tmp_path / "data-2"
    assert (b1 / "empty_dir").is_dir() or (b2 / "empty_dir").is_dir()


def test_exclude_top_level_pattern(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"keep")
    (target / "skip.log").write_bytes(b"skip")

    rc = main([str(target), "1", "--exclude", "*.log"])
    assert rc == 0

    bucket = tmp_path / "data-1"
    assert (bucket / "keep.txt").is_file()
    assert not (bucket / "skip.log").exists()
    assert (target / "skip.log").is_file()


def test_exclude_only_top_level_not_nested(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "sub").mkdir()
    (target / "sub" / "nested.log").write_bytes(b"x")

    rc = main([str(target), "1", "--exclude", "*.log"])
    assert rc == 0

    assert (tmp_path / "data-1" / "sub" / "nested.log").is_file()


def test_invalid_num_parts(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    rc = main([str(target), "0"])
    assert rc == 1


def test_missing_target(tmp_path: Path) -> None:
    rc = main([str(tmp_path / "nope"), "2"])
    assert rc == 1


def test_no_items(tmp_path: Path, capsys) -> None:
    target = tmp_path / "data"
    target.mkdir()
    rc = main([str(target), "2"])
    assert rc == 0
    assert "No items found" in capsys.readouterr().out


def test_more_buckets_than_items_creates_empty_buckets(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "only.bin").write_bytes(b"x")
    rc = main([str(target), "3"])
    assert rc == 0
    for i in (1, 2, 3):
        assert (tmp_path / f"data-{i}").is_dir()


def test_bin_pack_deterministic_lowest_index_wins_ties() -> None:
    items = [
        WorkItem(100, "a"),
        WorkItem(50, "b"),
        WorkItem(50, "c"),
        WorkItem(30, "d"),
    ]
    buckets = _bin_pack(items, 2)
    sizes = [sum(i.size for i in b) for b in buckets]
    assert sizes == [130, 100]
    assert [i.rel_path for i in buckets[0]] == ["a", "d"]
    assert [i.rel_path for i in buckets[1]] == ["b", "c"]


def test_collect_work_items_ordering(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "b.txt").write_bytes(b"x" * 50)
    (target / "a").mkdir()
    (target / "a" / "c").write_bytes(b"x" * 10)
    (target / "a" / "d").write_bytes(b"x" * 20)

    items = _collect_work_items(target, [])
    assert [i.rel_path for i in items] == ["a/c", "a/d", "b.txt"]


def test_idempotent_double_split_is_a_no_op(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "f.bin").write_bytes(b"x" * 50)

    rc1 = main([str(target), "2"])
    assert rc1 == 0
    rc2 = main([str(target), "2"])
    assert rc2 == 0
