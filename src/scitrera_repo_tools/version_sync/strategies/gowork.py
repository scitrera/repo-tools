"""Keep unpublished sibling versions resolvable only in the development workspace."""
from pathlib import Path
import re

_BEGIN = "// BEGIN repo-tools local module replacements"
_END = "// END repo-tools local module replacements"


def update_gowork(path: Path, version: str, dry_run: bool):
    del version
    text = path.read_text()
    # Use go.work's explicitly listed directories; never walk an enclosing repo.
    clean = re.sub(r"//[^\n]*", "", text)
    directories = re.findall(r"(?m)^use\s+([^\s(]+)", clean)
    for block in re.findall(r"(?ms)^use\s*\((.*?)^\)", clean):
        directories.extend(line.strip().strip('"') for line in block.splitlines() if line.strip())
    modules = {}
    sources = []
    for directory in directories:
        source = (path.parent / directory / "go.mod").read_text()
        module = re.search(r"(?m)^module\s+(\S+)", source)
        if module is None:
            raise ValueError(f"{directory}/go.mod has no module declaration")
        modules[module[1]] = directory
        sources.append(source)
    rows = set()
    for source in sources:
        for module, version in re.findall(r"(?m)^\s*(?:require\s+)?(\S+)\s+(v\S+)", source):
            if module in modules:
                rows.add(f"\t{module} {version} => {modules[module]}")
    block = _BEGIN + "\nreplace (\n" + "\n".join(sorted(rows)) + "\n)\n" + _END
    if _BEGIN in text or _END in text:
        if text.count(_BEGIN) != 1 or text.count(_END) != 1 or text.index(_BEGIN) > text.index(_END):
            raise ValueError(f"{path}: malformed managed workspace block")
        start, end = text.index(_BEGIN), text.index(_END) + len(_END)
        updated = text[:start] + block + text[end:]
    else:
        updated = text.rstrip() + "\n\n" + block + "\n"
    changed = updated != text
    if changed and not dry_run:
        path.write_text(updated)
    return changed, "workspace replacements" if changed else None
