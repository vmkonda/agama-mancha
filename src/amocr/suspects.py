"""Find lines worth a second look, from the text alone (no Claude, no tokens).

Every line of a book gets a score from independent signals:

  lookalike  a word that is rare in this book while a look-alike of it is common (देवो/देवी,
             बादि/आदि, अमराचित/अमरार्चित). The book is its own dictionary. Comes with a fix.
             Which letters look alike depends on the typeface: they come from the book's
             profile and from its own corrections, never from a built-in list.
  metre      a verse line with the wrong syllable count, if the book's profile sets one
             (16 for anuṣṭubh half-verses printed one per line).
  context    a common word whose look-alike is also common (को/की, हो/ही), where the next word
             says which: "की तरह" is far more usual in the book than "को तरह".
  verse_no   a verse number out of sequence (३५, ३६, ३९, ३८ ...).
  tesseract  Tesseract read the same line very differently.
  rare       a word that occurs once and whose letter sequences are among the least usual
             for this book (a character model trained on the book's own text).

Confident look-alike fixes can go to Suggestions as rules; everything flagged can go to
Claude as an image check; the rest is ordinary proofreading.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from .catalog import Work
from .metrics import cer, normalize
from . import patterns as pat

CONS = "कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ"
IND = "अआइईउऊऋॠऌएऐओऔ"
STRIP = "॥।,.;:()'\"‘’“”-—!?"
# Measured on the pilot book's 42 known corrections (see docs/engines.md): look-alikes are precise,
# Tesseract disagreement catches more but also flags many correct lines.
WEIGHTS = {"lookalike": 3, "context": 3, "verse_no": 3, "metre": 2, "tesseract": 2, "rare": 1}
TESS_DIFF = 0.08
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def clean(w: str) -> str:
    return re.sub(r"[०-९0-9]+$", "", w.strip(STRIP))  # trailing footnote markers too


def syllables(s: str) -> int:
    s = re.sub(r"[०-९0-9।॥'‘’\-—,.;:()\s]", "", s)
    n = 0
    for i, ch in enumerate(s):
        if ch in IND:
            n += 1
        elif ch in CONS:
            j = i + 1
            if j < len(s) and s[j] == "़":  # nukta
                j += 1
            if not (j < len(s) and s[j] == "्"):
                n += 1
    return n


# Look-alike rules are per book (a typeface's habits), never built in. Each is [from, to, why]:
#   "^भा" -> "आ"   at the start of a word        "ो" -> "ी"   at any one position
#   "+र्"          insert a reph before any consonant (a dropped र्)
def profile(work: Work) -> dict:
    """The book's settings: {"lookalikes": [[from, to, why], ...], "metre": 16 | None}.
    Kept in the book's book.json (extra.profile); learned look-alikes are added from its corrections."""
    prof = dict((work.extra or {}).get("profile") or {})
    rules = [list(r) for r in prof.get("lookalikes", [])]
    for r in pat.load(work)["rules"]:  # fragments people corrected at least twice
        if r["kind"] == "fragment" and r["count"] >= 2 and len(r["from"]) <= 4:
            rules.append([r["from"], r["to"], "learned from corrections"])
    return {"lookalikes": rules, "metre": prof.get("metre")}


def lookalikes(w: str, rules: list[list[str]]):
    """Spellings the book's typeface (and the engine) confuse with w: (variant, why)."""
    out = []
    for frm, to, why in rules:
        if frm == "+र्":
            out += [(w[:i] + "र्" + w[i:], why) for i in range(1, len(w)) if w[i] in CONS and w[i - 1] != "्"]
        elif frm.startswith("^"):
            if w.startswith(frm[1:]) and len(w) > len(frm) - 1:
                out.append((to + w[len(frm) - 1:], why))
        else:
            i = w.find(frm)
            while i >= 0:
                out.append((w[:i] + to + w[i + len(frm):], why))
                i = w.find(frm, i + 1)
    return out


class CharModel:
    """A character 4-gram model of the book's own words: what letter sequences are normal here."""

    def __init__(self, freq: Counter, n: int = 4):
        import math

        self.n, self.log = n, math.log
        self.grams, self.ctx = Counter(), Counter()
        self.alphabet = set()
        for w, c in freq.items():
            s = "^" * (n - 1) + w + "$"
            self.alphabet.update(s)
            for i in range(n - 1, len(s)):
                self.grams[s[i - n + 1:i + 1]] += c
                self.ctx[s[i - n + 1:i]] += c
        self.v = len(self.alphabet) or 1
        self.words = freq

    def score(self, w: str) -> float:
        """Log-probability of the word (add-0.1 smoothing)."""
        s, n = "^" * (self.n - 1) + w + "$", self.n
        return sum(self.log((self.grams[s[i - n + 1:i + 1]] + 0.1) / (self.ctx[s[i - n + 1:i]] + 0.1 * self.v))
                   for i in range(n - 1, len(s)))

    def per_char(self, w: str) -> float:
        return self.score(w) / (len(w) + 1)

    def threshold(self, share: float) -> float:
        vals = sorted(self.per_char(w) for w in self.words if len(w) >= 3)
        return vals[int(len(vals) * share)] if vals else float("-inf")


def _vocab(work: Work) -> Counter:
    freq = Counter()
    for page in pat.pages(work):
        d = pat.draft(work, page)
        if d and not d["source"].startswith("tesseract"):
            freq.update(clean(t) for t in pat.tokens(d["text"]))
    from .brief import glossary

    for t in glossary(work):  # the book's key terms, spelled right, count as well known
        freq[t["term"]] += 50
    return freq


def _line_types(work: Work, page: int) -> list[str]:
    best = pat.best_reading(work, page)
    base = pat.base_result(work, page)
    for rec in (best[1] if best else None, base[1] if base else None):
        if rec and rec.get("lines") and all(ln.get("type") for ln in rec["lines"]):
            return [ln["type"] for ln in rec["lines"]]
    return []


def _tess_lines(work: Work, page: int) -> list[dict]:
    found = sorted((work.page_dir(page) / "ocr").glob("tesseract-*.json"))
    return json.loads(found[-1].read_text(encoding="utf-8")).get("lines", []) if found else []


def _overlap(a, b) -> float:
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return w * h / max(1, (a[2] - a[0]) * (a[3] - a[1])) if w > 0 and h > 0 else 0.0


def score_book(work: Work, pages: list[int] | None = None, min_ratio: float = 4.0, lm_margin: float = 2.0) -> list[dict]:
    """One entry per non-blank line: {page, n, text, type, score, reasons[], fixes[]}."""
    freq, prof = _vocab(work), profile(work)
    ctx = [(re.compile(context_regex(r)), r) for r in context_fixes(work)]
    lm = CharModel(freq)
    odd = lm.threshold(0.03)  # the least book-like 3% of words
    out, verse_seq = [], []
    for page in pages or pat.pages(work):
        d = pat.draft(work, page)
        if not d or d["source"].startswith("tesseract"):
            continue
        types, tess = _line_types(work, page), _tess_lines(work, page)
        rows = [ln for ln in d["text"].split("\n") if ln.strip()]
        for k, line in enumerate(rows):
            typ = types[k] if k < len(types) else "other"
            box = d["boxes"][k] if k < len(d["boxes"]) else None
            reasons, fixes = [], []
            for tok in line.split():
                w = clean(tok)
                if len(w) < 2:
                    continue
                # Look-alike: compare whole words first, then the word's letter sequences (catches compounds).
                cands = lookalikes(w, prof["lookalikes"])
                best = max(((freq[v], v, why) for v, why in cands), default=(0, "", ""))
                if not (best[0] >= 3 and best[0] >= min_ratio * freq[w]) and cands and len(w) >= 3:
                    lm_best = max(((lm.score(v) - lm.score(w), v, why) for v, why in cands), default=(0, "", ""))
                    if lm_best[0] >= lm_margin:
                        reasons.append(f"lookalike: {w} → {lm_best[1]} reads more like this book ({lm_best[2]})")
                        fixes.append({"from": w, "to": lm_best[1], "why": lm_best[2], "seen": 0, "rare": freq[w]})
                        continue
                if best[0] >= 3 and best[0] >= min_ratio * freq[w]:
                    reasons.append(f"lookalike: {w} ({freq[w]}x) → {best[1]} ({best[0]}x), {best[2]}")
                    fixes.append({"from": w, "to": best[1], "why": best[2], "seen": best[0], "rare": freq[w]})
                elif freq[w] <= 1 and len(w) >= 3 and not re.search(r"[०-९0-9]", w) and lm.per_char(w) < odd:
                    reasons.append(f"rare: {w} is unusual for this book")
            for rx, r in ctx:
                if rx.search(line):
                    reasons.append(f"context: {r['from']} {r['next']} → {r['to']} {r['next']} ({r['to']} {r['next']} {r['seen']}x in this book)")
                    fixes.append({"from": r["from"], "to": r["to"], "why": "context", "seen": r["seen"], "rare": r["count"]})
            if typ == "verse" and prof["metre"]:
                n = syllables(line)
                if n and n != prof["metre"]:
                    reasons.append(f"metre: {n} syllables, not {prof['metre']}")
                m = re.search(r"॥\s*([०-९0-9]+)\s*॥\s*$", line)
                if m:
                    verse_seq.append((int(m.group(1).translate(DIGITS)), len(out)))
            if box and tess:
                hit = max(tess, key=lambda t: _overlap(box, t["bbox"]))
                if _overlap(box, hit["bbox"]) > 0.5 and cer(normalize(hit["text"]), normalize(line), ignore_space=True) > TESS_DIFF:
                    reasons.append("tesseract: reads this line differently")
            out.append({"page": page, "n": k + 1, "text": line, "type": typ, "reasons": reasons, "fixes": fixes})
    for i in range(1, len(verse_seq) - 1):  # a number that breaks an otherwise steady sequence
        (a, _), (b, idx), (c, _) = verse_seq[i - 1], verse_seq[i], verse_seq[i + 1]
        if b != a + 1 and c == a + 2:
            out[idx]["reasons"].append(f"verse_no: ॥ {b} ॥ between {a} and {c}")
    for e in out:
        e["score"] = sum(WEIGHTS[r.split(":")[0]] for r in e["reasons"])
    return out


def context_fixes(work: Work, min_seen: int = 3, ratio: float = 4.0) -> list[dict]:
    """Common words that a look-alike turns into another common word (को/की, हो/ही): only the
    next word can tell them apart. Returns {from, to, next, count, seen} where "to next" is
    far more usual in this book than "from next"."""
    rules = profile(work)["lookalikes"]
    uni, big = Counter(), Counter()
    for page in pat.pages(work):
        d = pat.draft(work, page)
        if d and not d["source"].startswith("tesseract"):
            toks = [clean(t) for t in pat.tokens(d["text"])]
            uni.update(toks)
            big.update(zip(toks, toks[1:]))
    pairs = {(a, v, why) for a, c in uni.items() if c >= 5 and len(a) <= 6
             for v, why in lookalikes(a, [r for r in rules if r[0] != "+र्"]) if uni[v] >= 20 and v != a}
    out = []
    for a, v, why in pairs:
        for (x, nxt), c in big.items():
            if x == a and nxt and big[(v, nxt)] >= min_seen and big[(v, nxt)] >= ratio * c:
                out.append({"from": a, "to": v, "next": nxt, "count": c, "seen": big[(v, nxt)], "why": why})
    return sorted(out, key=lambda r: -r["count"])


def context_regex(r: dict) -> str:
    b = pat.BOUNDARY
    return rf"(?<![^{b}]){re.escape(r['from'])}(?=[ \t]+{re.escape(r['next'])}(?![^{b}]))"


def known_errors(work: Work) -> dict[tuple[int, int], tuple[str, str]]:
    """Lines whose engine reading was corrected (saved text or a Claude review): (page, n) -> (engine, corrected)."""
    out = {}
    for page in pat.pages(work):
        base = pat.base_result(work, page)
        if not base or not base[0].startswith("surya"):
            continue
        t, _ = pat.gt_paths(work, page)
        corrected = t.read_text(encoding="utf-8") if t.exists() else None
        if corrected is None:
            for prefix in pat.CORRECTED:
                found = sorted((work.page_dir(page) / "ocr").glob(f"{prefix}*.json"))
                if found:
                    corrected = json.loads(found[-1].read_text(encoding="utf-8"))["text"]
                    break
        if corrected is None:
            continue
        a = [ln for ln in base[1]["text"].split("\n") if ln.strip()]
        b = [ln for ln in corrected.split("\n") if ln.strip()]
        if len(a) != len(b):
            continue
        for k, (x, y) in enumerate(zip(a, b)):
            if normalize(x).replace(" ", "") != normalize(y).replace(" ", ""):
                out[(page, k + 1)] = (x, y)
    return out


def evaluate(work: Work, threshold: int = 2) -> dict:
    """How many known corrections the scorer would have flagged, scoring the engine's reading."""
    errs = known_errors(work)
    pages = sorted({p for p, _ in errs})
    # Score what the engine read, not the corrected text.
    saved = {}
    for p in pages:
        for path in pat.gt_paths(work, p):
            if path.exists():
                saved[path] = path.read_bytes()
                path.rename(path.with_name(path.name + ".eval-hidden"))
    try:
        hidden = {p for p in pages for prefix in pat.CORRECTED for _ in (work.page_dir(p) / "ocr").glob(f"{prefix}*.json")}
        moved = []
        for p in hidden:
            for prefix in pat.CORRECTED:
                for f in (work.page_dir(p) / "ocr").glob(f"{prefix}*.json"):
                    f.rename(f.with_name(f.name + ".eval-hidden"))
                    moved.append(f)
        scored = {(e["page"], e["n"]): e for e in score_book(work, pages)}
    finally:
        for f in moved:
            f.with_name(f.name + ".eval-hidden").rename(f)
        for path in saved:
            path.with_name(path.name + ".eval-hidden").rename(path)
    flagged = {k for k, e in scored.items() if e["score"] >= threshold}
    caught = sorted(k for k in errs if k in flagged)
    missed = sorted(k for k in errs if k not in flagged)
    return {"pages": pages, "lines": len(scored), "errors": len(errs), "flagged": len(flagged),
            "caught": caught, "missed": [(k, errs[k][0], errs[k][1]) for k in missed],
            "false_flags": len(flagged - set(errs))}
