"""Decide whether a PDF page's existing text layer is usable, so OCR can be skipped.

Legacy Hindi fonts (Kruti Dev, Chanakya, Shree-Dev...) store Devanagari as Latin
code points, so "has text" is not enough: the text must actually be Devanagari
Unicode or plausible IAST.
"""

from __future__ import annotations

import unicodedata

IAST_MARKS = set("āīūṛṝḷḹṃḥṅñṭḍṇśṣĀĪŪṚṜḶḸṂḤṄÑṬḌṆŚṢ")


def _is_devanagari(ch: str) -> bool:
    cp = ord(ch)
    return 0x0900 <= cp <= 0x097F or 0xA8E0 <= cp <= 0xA8FF or 0x1CD0 <= cp <= 0x1CFF


def classify(text: str, min_chars: int = 50) -> str:
    """Return one of: 'none', 'devanagari', 'iast', 'suspect'.

    'none' and 'suspect' pages go to OCR.
    """
    text = unicodedata.normalize("NFC", text)
    letters = [c for c in text if c.isalpha() or unicodedata.category(c).startswith("M")]
    if len(letters) < min_chars:
        return "none"
    deva = sum(_is_devanagari(c) for c in letters) / len(letters)
    if deva >= 0.8:
        return "devanagari"
    latin = [c for c in letters if not _is_devanagari(c)]
    iast = sum(c in IAST_MARKS for c in latin) / max(len(latin), 1)
    # Real IAST Sanskrit has a diacritic every handful of letters; legacy-font junk has none.
    if deva < 0.2 and iast >= 0.03:
        return "iast"
    return "suspect"
