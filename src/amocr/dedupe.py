"""Books that are on this machine twice (same PDF, two ids), and merging one into the other.

A merge copies everything the kept book doesn't have yet (page readings, saved text, Claude
packets, rules) and never overwrites: a file that exists in both with different content is a
conflict, and then nothing is removed. Otherwise the duplicate's folder (and its copy of the
PDF) moves to data/trash/, and data/merged.json records the old id, which keeps working as
an alias. Only this machine changes; nothing on Proton Drive is touched.
"""

from __future__ import annotations

import filecmp
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Work, data_dir, load_works

SKIP = {"book.json", "inventory.jsonl"}      # the kept book's own records
SKIP_DIRS = {"export"}                        # rebuilt on every push


def merged_path() -> Path:
    return data_dir() / "merged.json"


def duplicates() -> list[list[Work]]:
    """Groups of books with the same PDF checksum, the one with the most pages first."""
    by_sha: dict[str, list[Work]] = {}
    for w in load_works(include_merged=False).values():
        if w.sha256 and len(w.sha256) == 64:
            by_sha.setdefault(w.sha256, []).append(w)
    return [sorted(g, key=lambda w: -_pages(w)) for g in by_sha.values() if len(g) > 1]


def _pages(w: Work) -> int:
    d = w.workdir / "pages"
    return sum(1 for _ in d.iterdir()) if d.exists() else 0


def _files(root: Path):
    if not root.exists():
        return
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if f.is_file() and rel.parts[0] not in SKIP_DIRS and rel.as_posix() not in SKIP and f.name != ".DS_Store":
            yield rel


# A person's work: if both books have it and it differs, a merge must not pick one silently.
PEOPLES = ("groundtruth/", "patterns.json", "glossary.json", "brief.md", "chat.jsonl", "rules")


def _same_reading(a: Path, b: Path) -> bool:
    """An engine reading is the same if its text is; the book id, time and operator don't matter."""
    if a.suffix != ".json":
        return False
    try:
        return json.loads(a.read_text(encoding="utf-8")).get("text") == json.loads(b.read_text(encoding="utf-8")).get("text")
    except (ValueError, OSError):
        return False


def plan(dup: Work, keep: Work) -> dict:
    """What a merge would do: files to copy, files the same, machine outputs where the kept book's
    version wins (the other goes to trash with the duplicate), and conflicts in people's work."""
    copy, kept, conflicts = [], [], []
    same = 0
    for rel in _files(dup.workdir):
        src, dst = dup.workdir / rel, keep.workdir / rel
        r = rel.as_posix()      # "groundtruth/p0001.txt" on Windows too
        if not dst.exists():
            copy.append(r)
        elif filecmp.cmp(src, dst, shallow=False) or _same_reading(src, dst):
            same += 1
        elif r.startswith(PEOPLES):
            conflicts.append(r)
        else:
            kept.append(r)
    return {"copy": copy, "same": same, "kept": kept, "conflicts": conflicts}


def merge(dup: Work, keep: Work, dry_run: bool = False) -> dict:
    if dup.id == keep.id:
        raise SystemExit("that's the same book")
    if not (dup.sha256 and dup.sha256 == keep.sha256):
        raise SystemExit(f"{dup.id} and {keep.id} are different PDFs (checksums differ); refusing to merge")
    if dup.restricted != keep.restricted:
        raise SystemExit(f"{dup.id} and {keep.id} differ in 'restricted'; settle that first")
    p = plan(dup, keep)
    if dry_run or p["conflicts"]:
        return p | {"done": False}
    for rel in p["copy"]:
        dst = keep.workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dup.workdir / rel, dst)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash = data_dir() / "trash" / f"{dup.id}-{stamp}"
    trash.mkdir(parents=True)
    if dup.workdir.exists():
        shutil.move(str(dup.workdir), trash / "work")
    if dup.source.exists() and dup.source != keep.source:
        if keep.source.exists():
            shutil.move(str(dup.source), trash / dup.source.name)
        else:
            dup.source.rename(keep.source)
    m = json.loads(merged_path().read_text(encoding="utf-8")) if merged_path().exists() else {}
    m[dup.id] = {"into": keep.id, "at": stamp, "trash": str(trash.relative_to(data_dir()))}
    merged_path().write_text(json.dumps(m, indent=1), encoding="utf-8")
    return p | {"done": True, "trash": str(trash)}
