"""A book's languages, and so the Tesseract models it is read with.

Each book records its languages (book.json, `languages`): Tesseract codes such as san, hin, eng.
They decide the models every Tesseract reading of the book uses, wherever it runs: `amocr ocr`,
`amocr claude-next`, and OCR workers taking the book's pages from a server's queue (the job
carries them). They also go into the reading's label (tesseract-san+hin+eng-psm3-…), so which
models made a reading is never in doubt.

  Devanagari only                      san+hin      (the default, as before)
  English, or Sanskrit in IAST         eng
  Devanagari with English commentary   san+hin+eng  (a little slower; reads both)

A newly fetched book gets them from the scripts its inventory saw on sample pages (and the
word "English" or "translation" in its title); `amocr languages <book> …` sets them by hand.
Surya needs none: it reads any script, but it places its lines with Tesseract's boxes, read with
the same models.
"""

from __future__ import annotations

import re

from .catalog import Work

DEFAULT = ["san", "hin"]
ALIASES = {"sa": "san", "hi": "hin", "en": "eng", "iast": "eng", "english": "eng", "sanskrit": "san", "hindi": "hin"}
CODE = re.compile(r"[a-z]{3}(_[a-z]+)?")      # Tesseract's model names: eng, san, hin, script_latin ...


def normalize(codes: list[str]) -> list[str]:
    """Tesseract codes, in order, without repeats; aliases (en, iast …) mapped. Raises on nonsense."""
    out = []
    for c in codes:
        c = ALIASES.get(c.strip().lower(), c.strip().lower())
        if not CODE.fullmatch(c):
            raise ValueError(f"not a Tesseract language code: {c!r} (e.g. san, hin, eng)")
        if c not in out:
            out.append(c)
    return out


def tesseract_langs(work: Work | None) -> str:
    """The -l argument for this book's Tesseract readings, e.g. "san+hin+eng"."""
    try:
        codes = normalize(list(work.languages or [])) if work else []
    except ValueError:
        codes = []
    return "+".join(codes or DEFAULT)


def suggest(facts: dict | None, title: str = "") -> list[str]:
    """Languages from what the inventory saw: the scripts on sample scanned pages, the text layer's
    script, and the title (an English translation or commentary often says so)."""
    facts = facts or {}
    seen = facts.get("scripts_seen") or {}
    script = facts.get("script") or ""
    deva = bool(seen.get("Devanagari")) or script == "Devanagari"
    latin = bool(seen.get("Latin")) or script.startswith("Latin")
    english = bool(re.search(r"\benglish\b|\btransl", title, re.I))
    out = list(DEFAULT) if deva or not (latin or english) else []
    if latin or english:
        out.append("eng")
    return out
