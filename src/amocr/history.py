"""Every save of a page's text, kept: groundtruth/pNNNN.history.jsonl, one version per line.

Each version: {"v", "at", "by", "status", "note", "how", "text"}, where "how" says what saved it
(save = Proofread, suggestions = accepted rule fixes, chat = a fix applied from the chat, before
history = the text a page already had when history began). Nothing is ever removed; the file travels
with the book on push, like the rest of groundtruth/.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import ladder
from .catalog import Work


def path(work: Work, page: int) -> Path:
    return work.gt_dir / f"p{page:04d}.history.jsonl"


def load(work: Work, page: int) -> list[dict]:
    f = path(work, page)
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _append(work: Work, page: int, rec: dict) -> None:
    f = path(work, page)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record(work: Work, page: int, text: str, meta: dict, how: str) -> int:
    """Call before writing a new version of the page. Keeps the page's current text first, if it has
    text that history never saw, then the new version. Returns the new version's number."""
    versions = load(work, page)
    t = work.gt_dir / f"p{page:04d}.txt"
    m = t.with_suffix(".meta.json")
    if not versions and t.exists():
        old_meta = json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}
        old = {"v": 0, "at": old_meta.get("saved"), "by": old_meta.get("reviewer"), "status": ladder.of(old_meta),
               "note": old_meta.get("note") or "", "how": "before history", "text": t.read_text(encoding="utf-8")}
        _append(work, page, old)
        versions = [old]
    n = (versions[-1]["v"] + 1) if versions else 1
    _append(work, page, {"v": n, "at": meta.get("saved"), "by": meta.get("reviewer"), "status": ladder.of(meta),
                         "note": meta.get("note") or "", "how": how, "text": text.rstrip("\n") + "\n"})
    return n


def base_text(work: Work, page: int) -> tuple[str, str] | None:
    """The engine reading the page's text started from: the label in its meta, else the reading
    Proofread would start from. (label, text)."""
    from .patterns import DRAFT_ORDER

    m = work.gt_dir / f"p{page:04d}.meta.json"
    meta = json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}
    ocr = work.page_dir(page) / "ocr"
    label = meta.get("base")
    if label and (ocr / f"{label}.json").exists():
        return label, json.loads((ocr / f"{label}.json").read_text(encoding="utf-8"))["text"]
    for prefix in DRAFT_ORDER:
        found = sorted(ocr.glob(f"{prefix}*.json")) if ocr.exists() else []
        if found:
            return found[-1].stem, json.loads(found[-1].read_text(encoding="utf-8"))["text"]
    return None
