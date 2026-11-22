"""Character error rate against hand-corrected ground truth.

Both sides are compared after the same normalization, so the score measures
reading errors, not whitespace or Unicode-composition differences.
"""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

# Visually identical forms that OCR engines emit interchangeably.
# Order matters: bars become dandas before danda pairs are merged.
_EQUIV = {
    "|": "।",  # ASCII bar -> danda
    "।।": "॥",  # two single dandas -> double danda
    "‘": "'",  # curly quotes -> straight
    "’": "'",
    "“": '"',
    "”": '"',
    "‌": "",  # ZWNJ
    "‍": "",  # ZWJ
}


def normalize(text: str, ignore_space: bool = False) -> str:
    text = unicodedata.normalize("NFC", text)
    for a, b in _EQUIV.items():
        text = text.replace(a, b)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    if ignore_space:
        text = re.sub(r"\s+", "", text)
    return text


def cer(hyp: str, ref: str, ignore_space: bool = False) -> float:
    """Edit distance / reference length, in grapheme-agnostic code points."""
    h, r = normalize(hyp, ignore_space), normalize(ref, ignore_space)
    if not r:
        return 0.0 if not h else 1.0
    return Levenshtein.distance(h, r) / len(r)
