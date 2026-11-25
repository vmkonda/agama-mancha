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


# --- IAST -> Devanagari (to show the reference's words to a proofreader) --------------------------

_C = {"kh": "ख", "gh": "घ", "ch": "छ", "jh": "झ", "ṭh": "ठ", "ḍh": "ढ", "th": "थ", "dh": "ध", "ph": "फ", "bh": "भ",
      "k": "क", "g": "ग", "ṅ": "ङ", "c": "च", "j": "ज", "ñ": "ञ", "ṭ": "ट", "ḍ": "ड", "ṇ": "ण", "t": "त", "d": "द",
      "n": "न", "p": "प", "b": "ब", "m": "म", "y": "य", "r": "र", "l": "ल", "v": "व", "ś": "श", "ṣ": "ष", "s": "स", "h": "ह"}
_V = {"ai": ("ऐ", "ै"), "au": ("औ", "ौ"), "a": ("अ", ""), "ā": ("आ", "ा"), "i": ("इ", "ि"), "ī": ("ई", "ी"),
      "u": ("उ", "ु"), "ū": ("ऊ", "ू"), "ṛ": ("ऋ", "ृ"), "ṝ": ("ॠ", "ॄ"), "ḷ": ("ऌ", "ॢ"), "e": ("ए", "े"), "o": ("ओ", "ो")}
_O = {"ṃ": "ं", "ḥ": "ः", "m̐": "ँ", "'": "ऽ", "’": "ऽ"}
_TOK = sorted(list(_C) + list(_V) + list(_O), key=len, reverse=True)


def deva(text: str) -> str:
    out, pending, k = [], False, 0
    t = text.lower()
    while k < len(t):
        tok = next((x for x in _TOK if t.startswith(x, k)), None)
        if tok in _C:
            if pending:
                out.append("्")
            out.append(_C[tok]); pending = True
        elif tok in _V:
            out.append(_V[tok][1] if pending else _V[tok][0]); pending = False
        else:
            if pending:
                out.append("्"); pending = False
            out.append(_O.get(tok, t[k]) if tok else t[k])
            tok = tok or t[k]
        k += len(tok)
    if pending:
        out.append("्")
    return "".join(out)


def _indexed(words: list[str], to_norm) -> tuple[str, list[int]]:
    """The normalised string of a list of words, and for each character the word it came from."""
    s, owner = "", []
    for i, w_ in enumerate(words):
        n = to_norm(w_)
        s += n
        owner += [i] * len(n)
    return s, owner


def _words_at(owner: list[int], i1: int, i2: int) -> list[int]:
    if not owner:
        return []
    if i2 > i1:
        return sorted(set(owner[i1:i2]))
    return [owner[min(i1, len(owner) - 1)]]      # an insertion: the word at that point


# --- Comparing -----------------------------------------------------------------------------------

# Footnote markers, as the viewer tints them: a digit stuck to a letter (योगी२) or right before a
# word (१षट्…). A lone ० after a letter is the abbreviation sign (क०) and stays.
_MARK_AFTER = re.compile(r"(?<=[\u0900-\u0963\u0971-\u097F])(?!०(?![०-९]))[०-९0-9]+")
_MARK_BEFORE = re.compile(r"(?:(?<=\s)|^)[१-९](?=[\u0905-\u0939])")


def strip_markers(line: str) -> str:
    return _MARK_BEFORE.sub("", _MARK_AFTER.sub("", line))


def compare_line(work: Work, line_deva: str, chapter: int | None) -> dict | None:
    """Like compare(), for a Devanagari line: each difference names the line's word(s) and the
    reference's word(s), both in Devanagari, so a proofreader can find them. Footnote markers
    are left out: they belong to this edition's apparatus, not to the text."""
    from .assemble import iast as to_iast

    words = [w_ for w_ in strip_markers(line_deva).split() if norm(to_iast(w_))]
    ours, owner = _indexed(words, lambda w_: norm(to_iast(w_)))
    c = compare(work, to_iast(" ".join(words)), chapter, normed=ours)
    if not c:
        return None
    rwords = c["text"].split()
    theirs, rowner = _indexed(rwords, norm)
    sm = difflib.SequenceMatcher(None, ours, theirs, autojunk=False)
    diffs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        ow = " ".join(words[i] for i in _words_at(owner, i1, i2))
        idx = _words_at(rowner, j1, j2)
        # GRETIL splits sandhi ("muhūrtād ety akhedataḥ"); a fragment ending in a virama reads
        # better with the word it joins.
        while idx and idx[-1] + 1 < len(rwords) and deva(rwords[idx[-1]]).endswith("्"):
            idx.append(idx[-1] + 1)
        rw = " ".join(deva(rwords[j]) for j in idx)
        if diffs and diffs[-1]["ours"] == ow:          # several differences in one word: say it once
            if rw not in diffs[-1]["ref"]:
                diffs[-1]["ref"] += " " + rw
            continue
        diffs.append({"ours": ow, "ref": rw})
    return c | {"diffs": diffs, "ref_deva": deva(c["text"])}


def compare(work: Work, line_iast: str, chapter: int | None, normed: str | None = None) -> dict | None:
    """The reference half-verse closest to this line, and where they differ (None: no match)."""
    from rapidfuzz import fuzz, process

    segs = segments(work)
    if not segs:
        return None
    n = normed if normed is not None else norm(line_iast)
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
