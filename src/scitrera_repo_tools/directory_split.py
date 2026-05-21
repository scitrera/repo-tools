"""Split a directory into N approximately-equal buckets via greedy bin-packing.

For each top-level entry of the target directory:
- File: treated as an atomic unit (assigned whole to a bucket).
- Directory: its children are each treated as atomic units, allowing the
  directory's contents to be spread across multiple buckets. The parent
  directory structure is recreated in each bucket as needed.
- Empty directory: preserved as a zero-size atomic unit.

`--exclude` patterns (fnmatch glob) apply only to top-level entries.

Deterministic: items are sorted descending by size (ties broken by ascending
path) and assigned greedily to the bucket with the smallest current size;
ties pick the lowest-index bucket.
"""

#  Copyright (c) 2026. Scitrera LLC. Licensed under 3-clause BSD license
#  (see LICENSE file at https://github.com/scitrera/repo-tools/blob/main/LICENSE)

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class WorkItem:
    size: int
    rel_path: str  # relative to target_dir; trailing "/" marks an empty-dir to preserve


def _directory_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in files:
            try:
                total += (root_path / name).lstat().st_size
            except OSError:
                pass
    return total


def _entry_size(path: Path) -> int:
    if path.is_symlink():
        return path.lstat().st_size
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return _directory_size(path)
    return 0


def _collect_work_items(target: Path, excludes: Sequence[str]) -> List[WorkItem]:
    items: List[WorkItem] = []
    entries = sorted(target.iterdir(), key=lambda p: p.name)
    for entry in entries:
        if any(fnmatch.fnmatch(entry.name, pat) for pat in excludes):
            continue
        if entry.is_symlink():
            items.append(WorkItem(entry.lstat().st_size, entry.name))
        elif entry.is_file():
            items.append(WorkItem(entry.stat().st_size, entry.name))
        elif entry.is_dir():
            children = sorted(entry.iterdir(), key=lambda p: p.name)
            if not children:
                items.append(WorkItem(0, entry.name + "/"))
            else:
                for child in children:
                    items.append(
                        WorkItem(_entry_size(child), f"{entry.name}/{child.name}")
                    )
    return items


def _bin_pack(items: List[WorkItem], num_parts: int) -> List[List[WorkItem]]:
    """Greedy: descending size, ascending path tie-break; assign to smallest bucket
    (lowest index wins ties)."""
    sorted_items = sorted(items, key=lambda i: (-i.size, i.rel_path))
    buckets: List[List[WorkItem]] = [[] for _ in range(num_parts)]
    sizes = [0] * num_parts
    for item in sorted_items:
        min_idx = 0
        for i in range(1, num_parts):
            if sizes[i] < sizes[min_idx]:
                min_idx = i
        buckets[min_idx].append(item)
        sizes[min_idx] += item.size
    return buckets


def _apply(target: Path, buckets: List[List[WorkItem]]) -> List[Path]:
    parent = target.parent
    base = target.name
    bucket_dirs: List[Path] = []
    for i in range(1, len(buckets) + 1):
        d = parent / f"{base}-{i}"
        d.mkdir(parents=True, exist_ok=True)
        bucket_dirs.append(d)

    for dest, bucket in zip(bucket_dirs, buckets):
        for item in bucket:
            if item.rel_path.endswith("/"):
                (dest / item.rel_path.rstrip("/")).mkdir(parents=True, exist_ok=True)
                continue
            if "/" in item.rel_path:
                (dest / item.rel_path).parent.mkdir(parents=True, exist_ok=True)
            src = target / item.rel_path
            shutil.move(str(src), str(dest / item.rel_path))

    for entry in list(target.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            try:
                entry.rmdir()
            except OSError:
                pass

    return bucket_dirs


def _human_size(n: int) -> str:
    """Compact size formatter (1024-base, K/M/G/T like `du -sh`)."""
    if n < 1024:
        return f"{n}B"
    value = float(n)
    for unit in ("K", "M", "G", "T", "P"):
        value /= 1024
        if value < 1024:
            return f"{value:.1f}{unit}"
    return f"{value:.1f}E"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="directory-split",
        description=(
            "Split a directory into N approximately-equal buckets, going one "
            "level deeper into top-level directories for better balance."
        ),
    )
    p.add_argument("directory", help="Directory to split")
    p.add_argument(
        "num_parts",
        type=int,
        help="Number of buckets (positive integer).",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="fnmatch pattern to exclude from top-level (repeatable).",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    target = Path(args.directory).resolve()
    num_parts: int = args.num_parts

    if not target.is_dir():
        print(f"Error: Directory {target} does not exist.", file=sys.stderr)
        return 1
    if num_parts <= 0:
        print(
            "Error: Number of parts must be a positive integer.",
            file=sys.stderr,
        )
        return 1

    print(f"Splitting {target} into {num_parts} parts (deep mode)...")

    items = _collect_work_items(target, args.exclude)
    if not items:
        print("No items found to split.")
        return 0

    buckets = _bin_pack(items, num_parts)
    bucket_dirs = _apply(target, buckets)

    print("Split completed.")
    for i, d in enumerate(bucket_dirs, start=1):
        print(f"Bucket {i}: {_human_size(_directory_size(d))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
