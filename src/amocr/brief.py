"""A short brief and glossary per book, so Claude (and new proofreaders) know what they're reading.

Claude never reads the whole book for this. `amocr brief <book> --sources` collects, cheaply:
the book's structure (front matter, contents, chapter starts and colophons, indexes, found from
the text), its most frequent words, and the text of a few chosen pages. Claude reads that once
and writes two files next to the book (never committed: they quote the book):

  data/works/<book>/brief.md        what the text is, its layout, chapters, conventions, typeface habits
  data/works/<book>/glossary.json   {"terms": [{"term": "मालिनी", "note": "..."}, ...]}

The glossary joins the book's dictionary in `amocr suspects`, and `amocr chat wait` points
Claude to the brief before it checks lines.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .catalog import Work
from . import patterns as pat

HEADINGS = ("विषय", "सूची", "अनुक्रम", "क्रमः", "प्रस्तावना", "भूमिका", "निवेदन", "पुरोवाक्", "उपोद्घात", "प्राक्कथन")


def brief_path(work: Work) -> Path:
    return work.workdir / "brief.md"


def glossary_path(work: Work) -> Path:
    return work.workdir / "glossary.json"


def glossary(work: Work) -> list[dict]:
    p = glossary_path(work)
    return json.loads(p.read_text(encoding="utf-8")).get("terms", []) if p.exists() else []


def structure(work: Work) -> dict:
    """Front matter and index headings, chapter starts and colophons, found from the text."""
    sections, chapters, colophons, prev = [], [], [], None
    pages = pat.pages(work)
    for p in pages:
        d = pat.draft(work, p)
        if not d:
            continue
        rows = [ln.strip() for ln in d["text"].split("\n") if ln.strip()]
        head = " ".join(rows[:3])
        hits = [h for h in HEADINGS if h in head]
        if hits and (p < pages[len(pages) // 10] or p > pages[-len(pages) // 8]):
            sections.append((p, rows[0] if len(rows[0]) > 3 else head[:60]))
        ch = next((r for r in rows[:3] if "धिकार" in r or "अध्याय" in r or "पटल" in r), None)
        if ch and ch != prev:
            chapters.append((p, ch))
            prev = ch
        colophons += [(p, r) for r in rows if re.match(r"इति\s", r) and len(r) > 12]
    return {"sections": sections, "chapters": chapters, "colophons": colophons}


def top_words(work: Work, n: int = 150) -> list[tuple[str, int]]:
    from .suspects import _vocab

    return [(w, c) for w, c in _vocab(work).most_common(n * 2) if len(w) >= 3][:n]


def sources(work: Work, pages: list[int]) -> str:
    st = structure(work)
    out = [f"# Sources for the brief of {work.id}: {work.title}", ""]
    out += ["## Front matter and index headings (page: first line)"] + [f"p{p}: {t}" for p, t in st["sections"]] + [""]
    out += ["## Running headers where they change (chapter starts; the engine misreads some)"]
    out += [f"p{p}: {t}" for p, t in st["chapters"]] + [""]
    out += ["## Colophons (chapter names)"] + [f"p{p}: {t}" for p, t in st["colophons"]] + [""]
    out += ["## Most frequent words (word: count)", ", ".join(f"{w}:{c}" for w, c in top_words(work)), ""]
    for p in pages:
        d = pat.draft(work, p)
        if d:
            out += [f"## Page {p} ({d['source']})", d["text"].strip(), ""]
    return "\n".join(out)
