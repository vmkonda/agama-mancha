"""Systematic fixes: learn from corrections, suggest the same fix everywhere else in the book.

1. mine():   compare each corrected page with the reading it started from (Surya, else
             Tesseract), word by word, and count the substitutions. Repeated ones are the
             engine's systematic mistakes (भाता for आता, -स्व for -त्व ...).
2. rules:    data/works/<book>/patterns.json. Mined word rules start enabled; mined
             fragment rules (the changed part of a word) start disabled, because they can
             match far too much. Claude or a person adds regex rules with `amocr rule add`.
3. suggest(): every place an enabled rule matches a page that isn't verified yet.
4. decide(): a person accepts (the page's draft text is updated) or rejects each one.

Nothing is applied without a person's yes: some "errors" are what the book prints.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfgmod
from .catalog import Work

BASES = ("surya-2.5-", "tesseract-")
CORRECTED = ("claude-code-review-", "claude-code-screen-")  # optional extra source for mining
BOUNDARY = r"\s।॥,;:()'\"‘’“”"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokens(s: str) -> list[str]:
    return re.sub(r"\s*([।॥])\s*", r" \1 ", s).split()


# ---- page text ---------------------------------------------------------------------------

def base_result(work: Work, page: int) -> tuple[str, dict] | None:
    ocr = work.page_dir(page) / "ocr"
    for prefix in BASES:
        found = sorted(ocr.glob(f"{prefix}*.json"))
        if found:
            return found[-1].stem, json.loads(found[-1].read_text(encoding="utf-8"))
    return None


def gt_paths(work: Work, page: int) -> tuple[Path, Path]:
    t = work.gt_dir / f"p{page:04d}.txt"
    return t, t.with_suffix(".meta.json")


# What Proofread starts from when a page has no saved text: Claude's reading, else Surya, else Tesseract.
DRAFT_ORDER = ("claude-code-review-", "claude-code-screen-", "claude-code-correct-", "claude-code-direct-") + BASES


def best_reading(work: Work, page: int) -> tuple[str, dict] | None:
    ocr = work.page_dir(page) / "ocr"
    for prefix in DRAFT_ORDER:
        found = sorted(ocr.glob(f"{prefix}*.json"))
        if found:
            return found[-1].stem, json.loads(found[-1].read_text(encoding="utf-8"))
    return None


def draft(work: Work, page: int) -> dict | None:
    """The text a proofreader works on, the same as the viewer's Proofread starts from:
    saved ground truth, else the best reading. Boxes come from that reading's lines when it
    has them, else from the base engine's."""
    t, m = gt_paths(work, page)
    best, base = best_reading(work, page), base_result(work, page)

    def boxes_of(rec):
        return [ln.get("bbox") for ln in (rec.get("lines") or [])]

    boxes = boxes_of(best[1]) if best and all(boxes_of(best[1])) and boxes_of(best[1]) else (boxes_of(base[1]) if base else [])
    if t.exists():
        meta = json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}
        from . import ladder

        # "verified" here means: leave the page alone (a person checked every line, or it has no text).
        return {"text": t.read_text(encoding="utf-8"), "source": "groundtruth",
                "verified": ladder.of(meta) in ("proofread", "validated", "blank"),
                "meta": meta, "boxes": boxes}
    if best:
        return {"text": best[1]["text"], "source": best[0], "verified": False, "meta": {}, "boxes": boxes}
    return None


def pages(work: Work) -> list[int]:
    d = work.workdir / "pages"
    return sorted(int(p.name) for p in d.glob("[0-9]*") if p.is_dir()) if d.exists() else []


# ---- mining ------------------------------------------------------------------------------

def word_pairs(base: str, corrected: str) -> list[tuple[str, str]]:
    a, b = tokens(base), tokens(corrected)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "replace" and i2 - i1 == j2 - j1:
            out += [(x, y) for x, y in zip(a[i1:i2], b[j1:j2]) if x != y]
    return out


def fragment(a: str, b: str) -> tuple[str, str] | None:
    """The changed part of a word, with one character of context on each side."""
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[-1 - s] == b[-1 - s]:
        s += 1
    lo, hia, hib = max(0, p - 1), len(a) - max(0, s - 1), len(b) - max(0, s - 1)
    fa, fb = a[lo:hia], b[lo:hib]
    if len(fa) < 2 or fa == fb or len(fa) >= len(a):  # too short to search for, or the whole word
        return None
    return fa, fb


def _rid(kind: str, frm: str, to: str) -> str:
    return kind[0] + hashlib.sha1(f"{kind}\0{frm}\0{to}".encode()).hexdigest()[:8]


def mine(work: Work, include_claude: bool = False) -> list[dict]:
    words, frags, kept = Counter(), Counter(), Counter()
    seen: dict[tuple, set] = defaultdict(set)
    for page in pages(work):
        base = base_result(work, page)
        if not base:
            continue
        sources = []
        t, _ = gt_paths(work, page)
        if t.exists():
            sources.append(t.read_text(encoding="utf-8"))
        if include_claude:
            for prefix in CORRECTED:
                for f in (work.page_dir(page) / "ocr").glob(f"{prefix}*.json"):
                    sources.append(json.loads(f.read_text(encoding="utf-8"))["text"])
                    break
        for corrected in sources[:1]:
            kept.update(tokens(corrected))  # how often each word stands as correct
            for a, b in word_pairs(base[1]["text"], corrected):
                words[(a, b)] += 1
                seen[("word", a, b)].add(page)
                fr = fragment(a, b)
                if fr:
                    frags[fr] += 1
                    seen[("fragment", *fr)].add(page)
    # A word the corrections also left standing elsewhere (ही, को ...) is often right as read:
    # keep that rule off until someone judges it.
    rules = [{"id": _rid("word", a, b), "kind": "word", "from": a, "to": b, "count": c,
              "pages": sorted(seen[("word", a, b)]), "source": "mined", "enabled": kept[a] < c,
              **({"note": f"'{a}' also stands unchanged {kept[a]}x in corrected text"} if kept[a] >= c else {})}
             for (a, b), c in words.items()]
    rules += [{"id": _rid("fragment", a, b), "kind": "fragment", "from": a, "to": b, "count": c,
               "pages": sorted(seen[("fragment", a, b)]), "source": "mined", "enabled": False}
              for (a, b), c in frags.items()]
    return rules


# ---- rules -------------------------------------------------------------------------------

def rules_path(work: Work) -> Path:
    return work.workdir / "patterns.json"


def load(work: Work) -> dict:
    p = rules_path(work)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {"rules": data.get("rules", []), "decisions": data.get("decisions", {})}


def save(work: Work, data: dict) -> None:
    rules_path(work).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def merge_mined(work: Work, include_claude: bool = False) -> dict:
    data = load(work)
    old = {r["id"]: r for r in data["rules"]}
    mined = {r["id"]: r for r in mine(work, include_claude)}
    out = []
    for rid, r in mined.items():
        if rid in old:  # keep the person's choices, refresh the evidence
            r = old[rid] | {"count": r["count"], "pages": r["pages"]}
        out.append(r)
    out += [r for rid, r in old.items() if rid not in mined and r["source"] != "mined"]
    data["rules"] = out
    save(work, data)
    return data


def add_rule(work: Work, kind: str, frm: str, to: str, note: str = "", source: str = "claude") -> dict:
    if kind not in ("word", "fragment", "regex"):
        raise ValueError("kind must be word, fragment or regex")
    if not frm:
        raise ValueError("empty pattern")
    if kind == "regex":
        re.compile(frm)
    data = load(work)
    rid = _rid(kind, frm, to)
    data["rules"] = [r for r in data["rules"] if r["id"] != rid]
    rule = {"id": rid, "kind": kind, "from": frm, "to": to, "count": 0, "pages": [], "source": source,
            "enabled": True, "note": note, "added": _now()}
    data["rules"].append(rule)
    save(work, data)
    return rule


def set_enabled(work: Work, rid: str, enabled: bool) -> None:
    data = load(work)
    for r in data["rules"]:
        if r["id"] == rid:
            r["enabled"] = enabled
            save(work, data)
            return
    raise LookupError(f"no rule {rid}")


# ---- suggestions -------------------------------------------------------------------------

def _matches(rule: dict, line: str):
    """(start, end, replacement) for each place the rule matches in the line."""
    if rule["kind"] == "word":
        pat = rf"(?<![^{BOUNDARY}]){re.escape(rule['from'])}(?![^{BOUNDARY}])"
        for m in re.finditer(pat, line):
            yield m.start(), m.end(), rule["to"]
    elif rule["kind"] == "fragment":
        i = line.find(rule["from"])
        while i >= 0:
            yield i, i + len(rule["from"]), rule["to"]
            i = line.find(rule["from"], i + 1)
    else:
        for m in re.finditer(rule["from"], line):
            yield m.start(), m.end(), m.expand(rule["to"])


def _occ_id(rid: str, page: int, line_no: int, start: int, line: str) -> str:
    return f"{rid}:{page}:{line_no}:{start}:{hashlib.sha1(line.encode()).hexdigest()[:8]}"


def suggest(work: Work, rule_id: str | None = None, limit: int = 500) -> list[dict]:
    data = load(work)
    rules = [r for r in data["rules"] if r["enabled"] and (rule_id is None or r["id"] == rule_id)]
    out = []
    for page in pages(work):
        d = draft(work, page)
        if not d or d["verified"] or d["source"].startswith("tesseract"):  # Tesseract's text is too noisy to patch
            continue
        k = -1
        for line_no, line in enumerate(d["text"].split("\n")):
            if not line.strip():
                continue
            k += 1
            box = d["boxes"][k] if k < len(d["boxes"]) else None
            for r in rules:
                for start, end, rep in _matches(r, line):
                    if line[start:end] == rep:
                        continue
                    oid = _occ_id(r["id"], page, line_no, start, line)
                    if oid in data["decisions"]:
                        continue
                    out.append({"id": oid, "rule": r["id"], "page": page, "line_no": line_no, "n": k + 1, "start": start, "end": end,
                                "line": line, "from": line[start:end], "to": rep, "bbox": box, "source": d["source"]})
                    if len(out) >= limit:
                        return out
    return out


def counts(work: Work) -> dict[str, int]:
    c = Counter(s["rule"] for s in suggest(work, limit=100_000))
    return dict(c)


def write_draft(work: Work, page: int, d: dict, lines: list[str], counter: str) -> None:
    """Save a page's draft text (never verified) and count what changed it."""
    t, m = gt_paths(work, page)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    meta = d["meta"] | {"reviewer": d["meta"].get("reviewer") or cfgmod.load().operator, "verified": False, "status": "draft",
                        "saved": _now(), "base": d["meta"].get("base") or (d["source"] if d["source"] != "groundtruth" else None),
                        counter: d["meta"].get(counter, 0) + 1}
    m.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def line_index(text: str, n: int) -> int | None:
    """Raw line index of the nth non-blank line (1-based), as counted in the viewer and `amocr line`."""
    k = 0
    for i, ln in enumerate(text.split("\n")):
        if ln.strip():
            k += 1
            if k == n:
                return i
    return None


def decide(work: Work, occ: dict, accept: bool) -> dict:
    """Record a decision; on accept, apply the fix to the page's draft text."""
    data = load(work)
    page, line_no, start = int(occ["page"]), int(occ["line_no"]), int(occ["start"])
    if accept:
        d = draft(work, page)
        if not d or d["verified"]:
            raise ValueError(f"p{page} is verified or has no text")
        lines = d["text"].split("\n")
        line = lines[line_no] if line_no < len(lines) else ""
        if line != occ["line"] or line[start:start + len(occ["from"])] != occ["from"]:
            raise ValueError(f"p{page} line {line_no + 1} changed since this suggestion was made; reload")
        lines[line_no] = line[:start] + occ["to"] + line[start + len(occ["from"]):]
        write_draft(work, page, d, lines, "suggestions_applied")
    data["decisions"][occ["id"]] = {"accept": accept, "from": occ["from"], "to": occ["to"], "at": _now()}
    save(work, data)
    return {"page": page, "accepted": accept}
