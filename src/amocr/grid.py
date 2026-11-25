"""The page grid: every page of a book with its status on the ladder, grouped by chapter, and how many
warnings it has (structure and reference). Statuses are quick to read; warnings take a few seconds
for a whole book, so they're cached per page and recomputed only when the page's text, the build or
the reference changes."""

from __future__ import annotations

import json
from pathlib import Path

from . import ladder
from .catalog import Work


def _meta(work: Work, p: int) -> tuple[Path, dict | None]:
    t = work.gt_dir / f"p{p:04d}.txt"
    m = t.with_suffix(".meta.json")
    if not t.exists():
        return t, None
    return t, json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}


def n_pages(work: Work) -> int:
    inv = work.workdir / "inventory.jsonl"
    return sum(1 for ln in inv.read_text(encoding="utf-8").splitlines() if ln.strip()) if inv.exists() else 0


def pages(work: Work) -> dict:
    from .assemble import latest_build

    rows, counts = [], {s: 0 for s in ladder.STATUSES}
    for p in range(1, n_pages(work) + 1):
        _, meta = _meta(work, p)
        st = ladder.of(meta) if meta is not None else "none"
        counts[st] += 1
        ocr = work.page_dir(p) / "ocr"
        rows.append({"page": p, "status": st, "saved_by": (meta or {}).get("reviewer"),
                     "proofread_by": (meta or {}).get("proofread_by"), "validated_by": (meta or {}).get("validated_by"),
                     "note": (meta or {}).get("note") or "", "saved": (meta or {}).get("saved"),
                     "claude": any(ocr.glob("claude-*.json")) if ocr.exists() else False})
    groups = []
    b = latest_build(work)
    info = json.loads((b / "build.json").read_text(encoding="utf-8")) if b and (b / "build.json").exists() else {}
    starts = sorted((int(p), int(ch)) for ch, p in (info.get("chapters") or {}).items())
    if starts:
        last_page = len(rows)
        tail = info.get("skipped_after_colophon") or []
        back = next((p for p in tail if p > starts[-1][0]), None)     # after the last chapter's colophon
        if starts[0][0] > 1:
            groups.append({"name": "Before chapter 1", "from": 1, "to": starts[0][0] - 1})
        for i, (p, ch) in enumerate(starts):
            end = (starts[i + 1][0] - 1) if i + 1 < len(starts) else ((back - 1) if back else last_page)
            groups.append({"name": f"Chapter {ch}", "from": p, "to": end})
        if back:
            groups.append({"name": "After the text", "from": back, "to": last_page})
    else:
        groups.append({"name": "All pages", "from": 1, "to": len(rows)})
    return {"pages": rows, "groups": groups, "counts": counts, "build": b.name if b else None,
            "done": counts["validated"] + counts["blank"], "total": len(rows)}


_CACHE: dict[tuple[str, int], tuple[tuple, dict]] = {}


def _signature(work: Work, p: int) -> tuple:
    from . import reference
    from .assemble import latest_build

    def mt(f: Path) -> float:
        return f.stat().st_mtime if f.exists() else 0.0

    ocr = work.page_dir(p) / "ocr"
    newest = max((mt(f) for f in ocr.glob("*.json")), default=0.0) if ocr.exists() else 0.0
    b = latest_build(work)
    return (mt(work.gt_dir / f"p{p:04d}.txt"), newest, b.name if b else None,
            mt(reference.ref_dir(work) / "segments.jsonl"))


def warnings(work: Work) -> dict[int, dict]:
    """Per page: {"structure": n, "reference": n}, from the page's best text. Only the text's own pages
    (chapters) are counted: front and back matter aren't verse and commentary, and aren't assembled."""
    from .assemble import page_structure, page_text

    groups = [g for g in pages(work)["groups"] if g["name"] not in ("Before chapter 1", "After the text")]
    text_pages = {p for g in groups for p in range(g["from"], g["to"] + 1)}
    out = {}
    for p in range(1, n_pages(work) + 1):
        if p not in text_pages:
            continue
        sig = _signature(work, p)
        hit = _CACHE.get((work.id, p))
        if hit and hit[0] == sig:
            out[p] = hit[1]
            continue
        got = page_text(work, p)
        c = {"structure": 0, "reference": 0}
        if got:
            for w_ in page_structure(work, p, "\n".join(ln["text"] for ln in got[0]))["warnings"]:
                c["reference" if w_.get("kind") == "reference" else "structure"] += 1
        _CACHE[(work.id, p)] = (sig, c)
        out[p] = c
    return out
