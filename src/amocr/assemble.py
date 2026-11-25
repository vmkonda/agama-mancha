"""Phase D: assemble a book's page texts into units (work/chapter/verse/layer) and save numbered builds.

Each page's best text is used: the person's saved text, else Claude's reading, else Surya's, else
Tesseract's. Lines are classed from the text itself (running header, verse, commentary, footnote,
colophon), because the layout is regular and the engines' own labels are not:

- a verse ends in a daṇḍa, and the last line of a verse carries its number (॥ ३४ ॥);
- commentary (Hindi) contains common Hindi words (है, के, की …), which Sanskrit verse doesn't;
- footnotes start with a number and a full stop (१. क० पु० …) at the foot of the page;
- the running header names the chapter (त्रयोदशोऽधिकारः); the colophon starts with इति.

Verses and commentary are two streams: a verse is complete at its number, a commentary passage at
the number of the verse(s) it explains (॥ ३५-३६ ॥), which gives `explains`; both run on across pages.
Builds are written to data/works/<id>/units/vNNN/ and never changed; an unchanged result makes no
new build. See docs/material-folder.md for the unit format.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import __version__
from . import config as cfgmod
from .catalog import Work, load_works
from .patterns import DRAFT_ORDER, gt_paths
from .book import now

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
ORDINALS = {
    "प्रथम": 1, "द्वितीय": 2, "तृतीय": 3, "चतुर्थ": 4, "पञ्चम": 5, "पंचम": 5, "षष्ठ": 6, "सप्तम": 7,
    "अष्टम": 8, "नवम": 9, "दशम": 10, "एकादश": 11, "द्वादश": 12, "त्रयोदश": 13, "चतुर्दश": 14,
    "पञ्चदश": 15, "पंचदश": 15, "षोडश": 16, "सप्तदश": 17, "अष्टादश": 18, "एकोनविंश": 19, "ऊनविंश": 19,
    "विंश": 20, "एकविंश": 21, "द्वाविंश": 22, "त्रयोविंश": 23, "चतुर्विंश": 24, "पञ्चविंश": 25,
    "षड्विंश": 26, "सप्तविंश": 27, "अष्टाविंश": 28, "एकोनत्रिंश": 29, "त्रिंश": 30,
}
# A chapter heading on a line of its own: "त्रयोदशोऽधिकारः", "अथ एकविंशतितमोऽधिकारः".
CHAPTER = re.compile(r"(?:अथ\s*)?(\S+?)(?:तितम)?(?:ोऽ|ो\s*ऽ|ाऽ|ः\s*)(?:धिकारः|ध्यायः|पटलः|परिच्छेदः|उल्लासः|प्रकाशः)\s*[:ः।]?")
VERSE_NO = re.compile(r"॥\s*([०-९0-9]+(?:\s*[-–]\s*[०-९0-9]+)?)\s*॥\s*$")
FOOTNOTE = re.compile(r"^\s*[०-९0-9]+\s*[.)]\s")
HINDI = {"है", "हैं", "था", "थे", "थी", "के", "की", "का", "को", "में", "से", "और", "यह", "वह", "यहाँ", "नहीं",
         "होता", "होती", "होते", "करता", "करते", "किया", "जाता", "जाती", "गया", "गयी", "ही", "भी", "इस", "उस",
         "इसका", "उसका", "इसी", "लिए", "कहा", "जो", "तो", "पर", "कर", "हो", "रहा", "रही", "हूँ", "हूं", "नामक",
         "चाहिये", "चाहिए", "वाला", "वाले", "वाली", "करना", "करने", "हुआ", "हुए", "हुई", "गये", "गए", "दिया",
         "जाये", "जायेगा", "जायेगी", "सकता", "सकते", "अर्थात्", "कहते", "कहलाते", "अपने", "अपना", "उनके", "इसके"}


def _bare(word: str) -> str:
    """Ordinals compared without anusvāra/candrabindu, which OCR often drops (विंश / विश)."""
    return word.replace("ं", "").replace("ँ", "")


_ORD = {_bare(k): v for k, v in ORDINALS.items()}


def chapter_of(text: str) -> int | None:
    m = CHAPTER.fullmatch(text.strip())
    return _ORD.get(_bare(m.group(1))) if m else None


def is_colophon(text: str) -> bool:
    """'इति श्रीमालिनीविजयोत्तरे तन्त्रे … ॥ १९ ॥' and the Hindi '… अधिकार परिपूर्ण ॥ १९ ॥'."""
    t = text.strip()
    return (t.startswith("इति") and ("तन्त्रे" in t or "धिकार" in t)) or (("परिपूर्ण" in t or "सम्पन्न" in t or "संपन्न" in t) and "धिकार" in t)


def is_hindi(text: str) -> bool:
    return any(w.strip("।॥,;:.!?()\"'") in HINDI for w in text.split())


def classify(lines: list[str]) -> list[str]:
    """One type per line: header, verse, commentary, footnote, colophon, signature."""
    types = ["commentary"] * len(lines)
    # Running header: the first lines while they are short (page number, chapter name, book title).
    i = 0
    while i < min(3, len(lines)) and (len(lines[i].split()) <= 2 and "।" not in lines[i]):
        types[i] = "header"
        i += 1
    # Footnotes: from the first line at the foot that starts "१." to the end.
    foot = next((k for k in range(i, len(lines)) if FOOTNOTE.match(lines[k]) and k >= len(lines) // 2), None)
    if foot is not None:
        for k in range(foot, len(lines)):
            types[k] = "footnote"
    end = foot if foot is not None else len(lines)
    # A short last line with no daṇḍa (a printer's signature mark like "१३ मा०").
    if foot is None and end > i and len(lines[end - 1].split()) <= 2 and not re.search(r"[।॥]", lines[end - 1]):
        types[end - 1] = "signature"
        end -= 1
    for k in range(i, end):
        t = lines[k].strip()
        if is_colophon(t) or (k > i and types[k - 1] == "colophon" and "धिकार" in t and not lines[k - 1].rstrip().endswith("॥")):
            types[k] = "colophon"
        elif not is_hindi(t) and (t.endswith("।") or t.endswith("॥") or VERSE_NO.search(t)):
            types[k] = "verse"
    # The end of a commentary passage can be a few words and the number ("करना चाहिये ॥ २ ॥"):
    # a verse line is longer than that.
    for k in range(i + 1, end):
        m = VERSE_NO.search(lines[k])
        if types[k] == "verse" and m and len(lines[k][:m.start()].split()) <= 3 and types[k - 1] == "commentary":
            types[k] = "commentary"
    # The first half of a verse may not end in a daṇḍa when the line is full: a non-Hindi line
    # directly before a numbered verse line is verse too.
    for k in range(end - 1, i, -1):
        if types[k] == "verse" and types[k - 1] == "commentary" and not is_hindi(lines[k - 1]) \
                and VERSE_NO.search(lines[k]):
            types[k - 1] = "verse"
    return types


# --- Devanagari -> IAST (for Sanskrit; Hindi would need schwa deletion) -----------------------

_CONS = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलळवशषसह",
                 "k kh g gh ṅ c ch j jh ñ ṭ ṭh ḍ ḍh ṇ t th d dh n p ph b bh m y r l ḷ v ś ṣ s h".split()))
_VOW = dict(zip("अआइईउऊऋॠऌएऐओऔ", "a ā i ī u ū ṛ ṝ ḷ e ai o au".split()))
_SIGN = dict(zip("ािीुूृॄॢेैोौ", "ā i ī u ū ṛ ṝ ḷ e ai o au".split()))
_OTHER = {"ं": "ṃ", "ः": "ḥ", "ँ": "m̐", "ऽ": "'", "।": "|", "॥": "||", "ॐ": "oṃ", "़": ""}


def iast(text: str) -> str:
    out, k = [], 0
    while k < len(text):
        ch = text[k]
        nxt = text[k + 1] if k + 1 < len(text) else ""
        if ch in _CONS:
            out.append(_CONS[ch])
            if nxt == "़":
                k += 1
                nxt = text[k + 1] if k + 1 < len(text) else ""
            if nxt == "्":
                k += 1
            elif nxt in _SIGN:
                out.append(_SIGN[nxt])
                k += 1
            else:
                out.append("a")
        elif ch in _VOW:
            out.append(_VOW[ch])
        elif ch in _SIGN:
            out.append(_SIGN[ch])
        elif ch in _OTHER:
            out.append(_OTHER[ch])
        else:
            out.append(ch.translate(DEVA_DIGITS))
        k += 1
    return "".join(out)


# --- Page texts ---------------------------------------------------------------------------------

def page_text(work: Work, page: int) -> tuple[list[dict], str, bool] | None:
    """The page's best lines [{text, n, bbox?}], where they came from, and whether a person verified them."""
    gt, meta = gt_paths(work, page)
    base = None
    ocr = work.page_dir(page) / "ocr"
    for prefix in DRAFT_ORDER:
        found = sorted(ocr.glob(f"{prefix}*.json")) if ocr.exists() else []
        if found:
            base = (found[-1].stem, json.loads(found[-1].read_text(encoding="utf-8")))
            break
    if gt.exists():
        texts = [ln for ln in gt.read_text(encoding="utf-8").split("\n") if ln.strip()]
        m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        source, verified = "groundtruth", bool(m.get("verified"))
    elif base:
        texts = [ln for ln in (base[1].get("text") or "").split("\n") if ln.strip()]
        source, verified = base[0], False
    else:
        return None
    # Positions from the engine's lines, when they line up one to one.
    blines = [ln for ln in (base[1].get("lines") or []) if (ln.get("text") or "").strip()] if base else []
    same = len(blines) == len(texts)
    return [{"text": t.strip(), "n": i + 1, **({"bbox": blines[i].get("bbox")} if same and blines[i].get("bbox") else {})}
            for i, t in enumerate(texts)], source, verified


def _join(parts: list[str]) -> tuple[str, int]:
    """Join a unit's lines; a word broken across lines with a hyphen is rejoined."""
    out, joins = "", 0
    for t in parts:
        if out.endswith("-") and not out.endswith(" -"):
            out, joins = out[:-1] + t, joins + 1
        else:
            out = f"{out} {t}" if out else t
    return out, joins


# --- Assembly -----------------------------------------------------------------------------------

def work_id(work: Work) -> tuple[str, bool]:
    """The permanent SL-… id when the catalog has one for this PDF; else the book id (provisional)."""
    for w in load_works(include_merged=True).values():
        if w.origin == "repo" and w.sha256 == work.sha256 and w.id != work.id:
            return w.id, False
    return (work.id, work.id.startswith("B-"))


def verse_key(raw: str, last: int) -> str:
    """'३५ - ३६' -> '35-36'. A footnote marker printed after the number ('३९-४०३') is dropped
    when the number would jump far past the last one."""
    parts = [x for x in re.split(r"[-–]", re.sub(r"\s+", "", raw).translate(DEVA_DIGITS)) if x]
    fixed = []
    for x in parts:
        ref = int(fixed[0]) if fixed else last
        if ref and len(x) > 1 and int(x) > ref + 30 and abs(int(x[:-1]) - ref) <= 30:
            x = x[:-1]
        fixed.append(x)
    return "-".join(fixed)


def _span(key: str) -> list[int]:
    a, _, b = key.partition("-")
    return list(range(int(a), int(b or a) + 1)) if a.isdigit() and (b or a).isdigit() and int(b or a) >= int(a) else []


def build_units(work: Work, pages: list[int], layers: dict, chapter_at: dict[int, int]) -> tuple[list[dict], dict]:
    """Verses and commentary are two streams. A verse is complete at its number (॥ ३४ ॥); a commentary
    passage ends with the number of the verse(s) it explains (॥ ३५-३६ ॥), and may run on across
    pages while the next verses are printed above it."""
    wid, provisional = work_id(work)
    langs = work.languages or ["san"]
    com_lang = langs[1] if len(langs) > 1 else langs[0]
    units: list[dict] = []
    ids: set[str] = set()
    report = {"pages_used": {}, "pages_without_text": [], "front_pages": [], "skipped_after_colophon": [], "chapters": {}, "hyphen_joins": 0,
              "unmarked_commentary": 0, "unnumbered_verse_lines": 0}
    chapter, closed = None, False
    verse_buf: list = []      # verse lines waiting for their number
    com_buf: list = []        # commentary lines waiting for their closing number
    last_no = 0

    def uid(*parts) -> str:
        base = "/".join(str(p) for p in parts)
        u, k = base, 2
        while u in ids:
            u, k = f"{base}~{k}", k + 1
        ids.add(u)
        return u

    def unit(verse, layer, lang, lines, **extra) -> dict:
        text, joins = _join([ln["text"] for ln, _ in lines])
        report["hyphen_joins"] += joins
        u = {"id": uid(wid, chapter, verse, layer), "work": wid, "chapter": chapter, "verse": verse, "layer": layer,
             "lang": lang, "text": text, **({"iast": iast(text)} if lang == "san" else {}), **extra,
             "pages": sorted({pi["page"] for _, pi in lines}),
             "lines": [{"page": pi["page"], "n": ln["n"], **({"bbox": ln["bbox"]} if ln.get("bbox") else {})}
                       for ln, pi in lines],
             "status": "verified" if all(pi["verified"] for _, pi in lines) else "draft",
             "source": sorted({pi["source"] for _, pi in lines}), "types": "guessed"}
        units.append(u)
        return u

    def flush():
        """End of a chapter: whatever is still open is saved, marked as such."""
        nonlocal verse_buf, com_buf
        if verse_buf:
            report["unnumbered_verse_lines"] += len(verse_buf)
            unit("unnumbered", layers["mula"], langs[0], verse_buf)
        if com_buf:
            report["unmarked_commentary"] += 1
            unit("unmarked", layers["commentary"], com_lang, com_buf, explains=[])
        verse_buf, com_buf = [], []

    for p in pages:
        got = page_text(work, p)
        if not got:
            report["pages_without_text"].append(p)
            continue
        lines, source, verified = got
        texts = [ln["text"] for ln in lines]
        types = classify(texts)
        found = next((c for t, ty in zip(texts, types) if ty == "header" for c in [chapter_of(t)] if c), None)
        new_ch = chapter_at.get(p) or (found if found and (chapter is None or found > chapter) else None)
        if new_ch and new_ch != chapter:
            flush()
            chapter, last_no, closed = new_ch, 0, False
            report["chapters"].setdefault(str(chapter), p)
        if chapter is None:
            report["front_pages"].append(p)
            continue
        if closed:      # after a chapter's colophon and before the next heading (or the back matter)
            report["skipped_after_colophon"].append(p)
            continue
        report["pages_used"][source] = report["pages_used"].get(source, 0) + 1
        pi = {"page": p, "source": source, "verified": verified}
        note = None
        for ln, ty in zip(lines, types):
            t = ln["text"]
            if ty in ("header", "signature"):
                continue
            if ty == "footnote":
                m = re.match(r"\s*([०-९0-9]+)\s*[.)]", t)
                if m or note is None:
                    n = m.group(1).translate(DEVA_DIGITS) if m else "x"
                    note = unit(f"p{p}", f"footnote-{n}", com_lang if is_hindi(t) else langs[0], [(ln, pi)], page=p)
                else:
                    note["text"] += " " + t
                    note["lines"].append({"page": p, "n": ln["n"]})
                continue
            if ty == "colophon":
                hindi = (is_hindi(t) or "परिपूर्ण" in t or "सम्पन्न" in t) and com_lang != langs[0]
                layer = layers["commentary"] if hindi else layers["mula"]
                prev = units[-1] if units and units[-1]["verse"] == "colophon" and units[-1]["layer"] == layer \
                    and units[-1]["chapter"] == chapter else None
                if prev:       # a colophon printed over two lines
                    prev["text"] += " " + t
                    prev["lines"].append({"page": p, "n": ln["n"], **({"bbox": ln["bbox"]} if ln.get("bbox") else {})})
                else:
                    unit("colophon", layer, com_lang if hindi else langs[0], (com_buf if hindi else verse_buf) + [(ln, pi)])
                    if hindi:
                        com_buf = []
                    else:
                        verse_buf = []
                # The chapter ends with the last layer's colophon (the commentary's, when there is one).
                if (hindi or com_lang == langs[0]) and re.search(r"[०-९0-9]+\s*॥?\s*$", t):
                    closed = True
                continue
            m = VERSE_NO.search(t)
            if ty == "verse":
                verse_buf.append((ln, pi))
                if m:
                    key = verse_key(m.group(1), last_no)
                    unit(key, layers["mula"], langs[0], verse_buf)
                    last_no = max([last_no] + _span(key))
                    verse_buf = []
                continue
            com_buf.append((ln, pi))
            if m:
                key = verse_key(m.group(1), last_no)
                unit(key, layers["commentary"], com_lang, com_buf,
                     explains=[f"{wid}/{chapter}/{v}/{layers['mula']}" for v in (_span(key) or [key])])
                com_buf = []
    flush()
    report["numbering"] = numbering(units, layers["mula"])
    report |= {"work_id": wid, "work_id_provisional": provisional}
    return units, report


def numbering(units: list[dict], mula: str) -> dict:
    """Per chapter: verse numbers missing or seen twice (each is a place to look at)."""
    out: dict[str, dict] = {}
    for ch in sorted({u["chapter"] for u in units}):
        nums = [n for u in units if u["chapter"] == ch and u["layer"] == mula for n in _span(u["verse"])]
        if not nums:
            continue
        seen: dict[int, int] = {}
        for n in nums:
            seen[n] = seen.get(n, 0) + 1
        out[str(ch)] = {"last": max(nums), "missing": sorted(set(range(1, max(nums) + 1)) - set(nums)),
                        "twice": sorted(n for n, k in seen.items() if k > 1)}
    return out


def builds_dir(work: Work) -> Path:
    return work.workdir / "units"


def latest_build(work: Work) -> Path | None:
    d = builds_dir(work)
    vs = sorted(d.glob("v[0-9][0-9][0-9]")) if d.exists() else []
    return vs[-1] if vs else None


def assemble(work: Work, pages: list[int] | None = None, commentary_layer: str | None = None,
             chapter_at: dict[int, int] | None = None) -> dict:
    """Build units for the book and save them as a new numbered build (unless nothing changed)."""
    if commentary_layer:
        work.extra.setdefault("layers", {})["commentary"] = commentary_layer
        if work.origin == "book":
            work.save()
    layers = {"mula": "mula", "commentary": "commentary"} | work.extra.get("layers", {})
    chapter_at = {int(k): v for k, v in (work.extra.get("chapter_at") or {}).items()} | (chapter_at or {})
    if pages is None:
        n = len([ln for ln in (work.workdir / "inventory.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]) \
            if (work.workdir / "inventory.jsonl").exists() else 0
        pages = list(range(1, n + 1))
    units, report = build_units(work, pages, layers, chapter_at)
    body = "".join(json.dumps(u, ensure_ascii=False) + "\n" for u in units)
    prev = latest_build(work)
    if prev and (prev / "units.jsonl").read_text(encoding="utf-8") == body:
        return {"build": prev.name, "new": False, "units": len(units), "path": str(prev)} | report
    out = builds_dir(work) / f"v{(int(prev.name[1:]) + 1) if prev else 1:03d}"
    out.mkdir(parents=True)
    (out / "units.jsonl").write_text(body, encoding="utf-8")
    counts: dict[str, int] = {}
    for u in units:
        kind = "footnote" if u["layer"].startswith("footnote-") else u["layer"]
        counts[kind] = counts.get(kind, 0) + 1
    build = {"build": out.name, "date": now(), "by": cfgmod.load().operator, "amocr_version": __version__,
             "pages": [pages[0], pages[-1]] if pages else [], "units": counts,
             "verified_units": sum(u["status"] == "verified" for u in units), "layers": layers} | report
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"build": out.name, "new": True, "units": len(units), "path": str(out)} | report


# --- For the proofreader: what the assembler will make of one page ----------------------------

def _context(work: Work, page: int) -> dict:
    """Chapter at this page and the last verse number before it, from the latest build."""
    b = latest_build(work)
    if not b:
        return {"chapter": None, "last_verse": 0}
    info = json.loads((b / "build.json").read_text(encoding="utf-8"))
    starts = sorted((p, int(ch)) for ch, p in (info.get("chapters") or {}).items())
    chapter = next((ch for p, ch in reversed(starts) if p <= page), None)
    last = 0
    mula = (info.get("layers") or {}).get("mula", "mula")
    for line in (b / "units.jsonl").read_text(encoding="utf-8").splitlines():
        u = json.loads(line)
        if u["chapter"] == chapter and u["layer"] == mula and u["pages"] and max(u["pages"]) < page:
            last = max([last] + _span(u["verse"]))
    return {"chapter": chapter, "last_verse": last, "build": b.name}


def page_structure(work: Work, page: int, text: str) -> dict:
    """Per line: its type and number, as the assembler sees it; and warnings worth a look."""
    lines = [t.strip() for t in text.split("\n") if t.strip()]
    types = classify(lines)
    ctx = _context(work, page)
    found = next((c for t, ty in zip(lines, types) if ty == "header" for c in [chapter_of(t)] if c), None)
    chapter = found or ctx["chapter"]
    last = 0 if found and found != ctx["chapter"] else ctx["last_verse"]
    printed = next((t.translate(DEVA_DIGITS) for t, ty in zip(lines, types)
                    if ty == "header" and t.translate(DEVA_DIGITS).strip().isdigit()), None)
    out, warnings, verses, comments = [], [], [], []
    for n, (t, ty) in enumerate(zip(lines, types), 1):
        tag = {"type": ty}
        m = VERSE_NO.search(t)
        if ty in ("verse", "commentary") and m:
            key = verse_key(m.group(1), last)
            span = _span(key)
            if ty == "verse":
                tag["verse"] = key
                if span and last and span[0] != last + 1:
                    warnings.append({"line": n, "text": f"verse {key} after verse {last}: a misread number?"})
                verses.append(key)
                last = max([last] + span)
            else:
                tag["explains"] = key
                comments.append(key)
                if span and span[-1] > last:
                    warnings.append({"line": n, "text": f"commentary on {key}, but the last verse so far is {last}"})
        elif ty == "footnote":
            fm = re.match(r"\s*([०-९0-9]+)", t)
            if fm:
                tag["note"] = fm.group(1).translate(DEVA_DIGITS)
        elif ty == "header" and chapter_of(t):
            tag["chapter"] = chapter_of(t)
        out.append(tag)
    # A verse number that isn't closed properly ("॥ ३८ ।", "। ३८ ॥", "॥ ३८"): the assembler can't see it.
    bad_no = re.compile(r"[।॥]\s*[०-९0-9]+(?:\s*[-–]\s*[०-९0-9]+)?\s*[।॥]?\s*$")
    for n, (t, tag) in enumerate(zip(lines, out), 1):
        if tag["type"] in ("verse", "commentary") and not VERSE_NO.search(t) and bad_no.search(t):
            warnings.insert(0, {"line": n, "text": f"verse number not between ॥ … ॥: «{bad_no.search(t).group(0).strip()}»"})
    # A verse line at the end of the page without a number simply runs on; one in the middle doesn't.
    for k in range(len(out) - 1):
        if out[k]["type"] == "verse" and "verse" not in out[k] and out[k + 1]["type"] not in ("verse",):
            if any(o["type"] == "verse" for o in out[k + 1:]):
                warnings.append({"line": k + 1, "text": "verse lines end here without a number (॥ N ॥)"})
    return {"lines": out, "chapter": chapter, "printed_page": printed, "verses": verses, "commentary": comments,
            "warnings": warnings, "build": ctx.get("build")}
