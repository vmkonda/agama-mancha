"""Reference e-texts: another typed edition of a book's root text, used to flag verse lines worth a look.

A reference (e.g. GRETIL's IAST e-text) is book data in data/works/<book>/reference/: the source
file as given, and segments.jsonl, one half-verse per line ({"key", "chapter", "text"}). Lines are
compared letter by letter after normalising what is spelling rather than reading (spaces, sandhi
spacing, punctuation, one sign for all nasals). A difference is a place to look at the print, never a
correction: editions differ, and the book is transcribed as printed. References are licensed by
their owners (GRETIL: CC BY-NC-SA) and never go into the repository.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .catalog import Work

MIN_SCORE = 60      # below this, a line isn't the same half-verse at all


def ref_dir(work: Work) -> Path:
    return work.workdir / "reference"


def info(work: Work) -> dict | None:
    f = ref_dir(work) / "reference.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# --- Parsing -------------------------------------------------------------------------------------

GRETIL_SEG = re.compile(r"(?:^|\s)(\d+)\.(\d+)([a-f]{2})?:\s*(.*?)(?=\s\d+\.\d+(?:[a-f]{2})?:|\n|$)")


def parse_gretil(text: str) -> list[dict]:
    """GRETIL plain text: '13.34ab: ity eṣā … 13.34cd: svadehaṃ …' (chapter.verse + pāda pair)."""
    out = []
    for m in GRETIL_SEG.finditer(text):
        body = m.group(4).strip()
        if body:
            out.append({"key": f"{m.group(1)}.{m.group(2)}{m.group(3) or ''}", "chapter": int(m.group(1)), "text": body})
    return out


def norm(t: str) -> str:
    """IAST with spelling differences removed; what's left is a difference in reading."""
    t = t.lower().replace("'", "").replace("’", "").replace("ṁ", "ṃ")
    t = re.sub(r"[0-9|.,;:!?()\[\]\-–—“”\"/]", " ", t)
    t = re.sub(r"[ṅñṇn](?=\s*[kgcjṭḍtdpbśṣsyrlvh])", "m", t)    # a class nasal before a consonant
    t = t.replace("ṃ", "m")                                    # one sign for all nasals
    return re.sub(r"\s+", "", t)


def add(work: Work, source: Path, name: str, url: str = "", licence: str = "", fmt: str = "gretil") -> dict:
    """Store a reference e-text for the book and split it into half-verses."""
    if fmt != "gretil":
        raise SystemExit(f"unknown format {fmt!r} (known: gretil)")
    text = source.read_text(encoding="utf-8")
    segs = parse_gretil(text)
    if not segs:
        raise SystemExit(f"{source}: no 'chapter.verse: text' segments found; is it GRETIL's plain-text form?")
    d = ref_dir(work)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, d / ("source" + source.suffix))
    (d / "segments.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segs), encoding="utf-8")
    meta = {"name": name, "url": url, "licence": licence, "format": fmt, "file": source.name,
            "segments": len(segs), "chapters": sorted({s["chapter"] for s in segs}),
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (d / "reference.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


@lru_cache(maxsize=8)
def _segments(path: str, mtime: float) -> tuple[tuple[str, int, str, str], ...]:
    rows = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    return tuple((r["key"], r["chapter"], r["text"], norm(r["text"])) for r in rows)


def segments(work: Work):
    f = ref_dir(work) / "segments.jsonl"
    return _segments(str(f), f.stat().st_mtime) if f.exists() else ()


# --- Comparing -----------------------------------------------------------------------------------

def compare(work: Work, line_iast: str, chapter: int | None) -> dict | None:
    """The reference half-verse closest to this line, and where they differ (None: no match)."""
    from rapidfuzz import fuzz, process

    segs = segments(work)
    if not segs:
        return None
    n = norm(line_iast)
    if len(n) < 8:
        return None
    pool = [s for s in segs if s[1] == chapter] or list(segs)
    hit = process.extractOne(n, [s[3] for s in pool], scorer=fuzz.ratio)
    if not hit or hit[1] < MIN_SCORE:
        pool = list(segs)
        hit = process.extractOne(n, [s[3] for s in pool], scorer=fuzz.ratio)
        if not hit or hit[1] < MIN_SCORE:
            return None
    key, _, text, rn = pool[hit[2]]
    sm = difflib.SequenceMatcher(None, n, rn, autojunk=False)
    diffs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            diffs.append({"ours": n[i1:i2], "ref": rn[j1:j2],
                          "context": n[max(0, i1 - 4):i1] + "[" + n[i1:i2] + "]" + n[i2:i2 + 4],
                          "ref_context": rn[max(0, j1 - 4):j1] + "[" + rn[j1:j2] + "]" + rn[j2:j2 + 4]})
    return {"key": key, "text": text, "score": round(hit[1]), "diffs": diffs}
