"""Which library PDFs need OCR (docs/plan.md, phase C).

Per PDF: page count, whether its text layer is usable (Devanagari or IAST Unicode, or
plain Latin text), and for scans the script, from Tesseract's script detection on a
few pages. A PDF whose pages mostly have no usable text needs OCR.

Facts are keyed by the PDF's SHA-1 and shared like the board: each person writes only
their own file, everyone reads all of them.

  shared: <material folder>/catalog/inventory/<operator>.json   {"operator", "updated", "pdfs": {sha1: facts}}
  local:  data/library/inventory/<operator>.json

The facts are measurements, never text from the book.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .catalog import data_dir
from .textcheck import IAST_MARKS, _is_devanagari, classify

VERSION = "inv2"  # inv2: OCR layers told apart, text-only screen
SUB = "inventory"
# Enough to tell English prose from legacy-font Devanagari (which reads like "dk;Z djrs gS").
STOPWORDS = set("the of and to in is that for it as with by on was this be are from or which an at not his "
                "their have has but its all one were they".split())
VERDICTS = {"ocr": "needs OCR", "text": "has a text layer", "mixed": "partly usable text", "empty": "no pages",
            "notpdf": "not a PDF"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def page_kind(text: str) -> str:
    """none / devanagari / iast / latin / suspect (legacy-font junk or unknown)."""
    k = classify(text)
    if k != "suspect":
        return k
    words = re.findall(r"[a-z]+", unicodedata.normalize("NFC", text).lower())
    if words and sum(w in STOPWORDS for w in words) / len(words) >= 0.12:
        return "latin"
    return k


OCR_PRODUCERS = re.compile(r"ocrmypdf|tesseract|abbyy|finereader|paper capture|omnipage|readiris|clearscan|"
                           r"google.*ocr|ocr", re.I)
DEVA_CONS = "\u0915-\u0939\u0958-\u095F\u0978-\u097F"
# A vowel sign or virama with no consonant before it: impossible in real Devanagari, common in bad OCR.
DEVA_BROKEN = re.compile(f"(?<![{DEVA_CONS}\u093C])[\u093E-\u094D\u0962\u0963]")
# ASCII, IAST, ISO 15919 (ṁ ē ō ...) and the accents of European languages.
LATIN_OK = (set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") | IAST_MARKS
            | set("ṁṀēōĒŌḻḺṉṈṟṙẏ") | set("éèêàâäçïîôöùûüñœæÉÈÀÇÖÜßáíóúÁÍÓÚ"))
GARBLED_DEVA = 0.01  # real Devanagari text scores 0.0 (proofread pages, Surya's reading)
GARBLED_LATIN = 0.01


def _letter_ok(c: str) -> bool:
    cp = ord(c)
    # Other Indic scripts (Bengali to Malayalam; Śāradā, Grantha, Siddham ...) are real text too.
    return c in LATIN_OK or 0x0980 <= cp <= 0x0DFF or 0x11000 <= cp <= 0x11FFF or _is_devanagari(c)


def screen(texts: list[str]) -> dict:
    """Text-only signs of a garbled text layer (no image needed).

    deva_broken: share of Devanagari letters that are vowel signs or viramas with no consonant
      before them: impossible in real text; typical of fonts that don't map back to Unicode.
    odd_letters: share of letters on Latin pages that are neither ASCII, IAST/ISO 15919, common
      accents nor another Indic script: leftovers of legacy fonts (Ë Ý Æ µ ...)."""
    deva = broken = latin = odd = 0
    for t in texts:
        t = unicodedata.normalize("NFC", t)
        d = sum(_is_devanagari(c) for c in t)
        deva += d
        broken += len(DEVA_BROKEN.findall(t))
        if d < len(t) * 0.2:
            letters = [c for c in t if c.isalpha()]
            latin += len(letters)
            odd += sum(not _letter_ok(c) for c in letters)
    return {"deva_broken": round(broken / deva, 4) if deva >= 200 else None,
            "odd_letters": round(odd / latin, 4) if latin >= 500 else None}


def garbled(sc: dict | None) -> bool:
    sc = sc or {}
    return (sc.get("deva_broken") or 0) >= GARBLED_DEVA or (sc.get("odd_letters") or 0) >= GARBLED_LATIN


def _osd(img: Path) -> tuple[str | None, float]:
    from .setup import models_present, tessdata_dir

    if not shutil.which("tesseract"):
        return None, 0.0
    args = ["tesseract", str(img), "-", "--psm", "0"]
    if models_present(["osd"]):
        args += ["--tessdata-dir", str(tessdata_dir())]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None, 0.0
    m = re.search(r"Script: (\w+)", out)
    c = re.search(r"Script confidence: ([\d.]+)", out)
    return (m.group(1) if m else None), (float(c.group(1)) if c else 0.0)


def summarize(pdf: Path, osd_pages: int = 3) -> dict:
    """The facts for one PDF."""
    import pymupdf

    t0 = time.time()
    with open(pdf, "rb") as f:
        head = f.read(1024)
    if b"%PDF" not in head:
        low = head.lower()
        what = ("a macOS placeholder: the real file was never uploaded" if head.startswith(b"bplist")
                else "a web page saved as .pdf (a blocked or failed download)" if b"<html" in low or b"<!doctype" in low
                else "no PDF header")
        return {"v": VERSION, "at": _now(), "pages": 0, "verdict": "notpdf", "why": what,
                "bytes": pdf.stat().st_size, "seconds": round(time.time() - t0, 1)}
    doc = pymupdf.open(pdf)
    kinds: Counter = Counter()
    scans = 0
    layer_pages = []  # usable text lying over a full-page scan: someone's OCR
    sample = []  # text of a few usable pages, for the text-only screen
    fonts: Counter = Counter()  # fonts of pages whose text layer isn't usable (legacy encodings)
    need = []  # pages that need OCR, for script detection
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        k = page_kind(text)
        kinds[k] += 1
        scans += bool(page.get_images())
        if k in ("devanagari", "iast", "latin"):
            area = page.rect.width * page.rect.height or 1
            if any(abs(im["bbox"][2] - im["bbox"][0]) * abs(im["bbox"][3] - im["bbox"][1]) >= 0.6 * area
                   for im in page.get_image_info()):
                layer_pages.append(i)
            if len(sample) < 40 and i % 3 == 0 or len(sample) < 3:
                sample.append(text)
        if k in ("none", "suspect"):
            need.append(i)
        if k == "suspect":
            for f in page.get_fonts():
                fonts[f[3].split("+", 1)[-1]] += 1
    n = doc.page_count
    usable = kinds["devanagari"] + kinds["iast"] + kinds["latin"]
    if not n:
        verdict = "empty"
    elif usable >= 0.9 * n:
        verdict = "text"
    elif usable <= 0.1 * n:
        verdict = "ocr"
    else:
        verdict = "mixed"
    scripts: Counter = Counter()
    if need and osd_pages:
        picks = sorted({need[int(len(need) * f)] for f in (0.25, 0.5, 0.75)})[:osd_pages]
        with tempfile.TemporaryDirectory(dir=data_dir()) as td:
            for p in picks:
                pix = doc[p - 1].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
                img = Path(td) / f"p{p}.png"
                pix.save(img)
                s, conf = _osd(img)
                if s and conf >= 2:
                    scripts[s] += 1
    why = None
    if verdict in ("ocr", "mixed"):
        legacy = kinds["suspect"] > kinds["none"]
        why = (f"text in a legacy font ({', '.join(n for n, _ in fonts.most_common(2))})" if legacy and fonts
               else "unusable text layer" if legacy else "scanned pages")
    meta = doc.metadata or {}
    producer = " / ".join(x for x in (meta.get("producer"), meta.get("creator")) if x)[:120] or None
    layer = None
    if usable:
        layer = "ocr" if len(layer_pages) >= 0.5 * usable or (producer and OCR_PRODUCERS.search(producer)) else "digital"
    text_script = max(("devanagari", "iast", "latin"), key=lambda k: kinds[k]) if usable else None
    return {
        "v": VERSION, "at": _now(), "pages": n, "scans": scans,
        "kinds": {k: kinds[k] for k in ("devanagari", "iast", "latin", "suspect", "none") if kinds[k]},
        "verdict": verdict, "why": why, "fonts": [n for n, _ in fonts.most_common(3)] or None,
        "layer": layer, "layer_pages": layer_pages if layer == "ocr" else None, "producer": producer,
        "screen": screen(sample) if usable else None,
        "script": scripts.most_common(1)[0][0] if scripts else ({"devanagari": "Devanagari", "iast": "Latin (IAST)", "latin": "Latin"}.get(text_script)),
        "scripts_seen": dict(scripts),
        "seconds": round(time.time() - t0, 1),
    }


# ---- storing and sharing (each person's own file) ---------------------------------------

def local_dir() -> Path:
    return data_dir() / "library" / SUB


def load_mine(operator: str) -> dict:
    from .board import file_name

    p = local_dir() / file_name(operator)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("operator") == operator:
            return d
    return {"operator": operator, "updated": None, "pdfs": {}}


def save_mine(mine: dict) -> Path:
    from .board import file_name

    local_dir().mkdir(parents=True, exist_ok=True)
    mine["updated"] = _now()
    p = local_dir() / file_name(mine["operator"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(mine, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def put(operator: str, sha1: str, facts: dict, update: bool = False) -> None:
    """Save one PDF's facts into this person's file, re-reading it first so two runs on
    this machine (the inventory and the quality check) don't overwrite each other."""
    mine = load_mine(operator)
    mine["pdfs"][sha1] = (mine["pdfs"].get(sha1, {}) | facts) if update else facts
    save_mine(mine)


def merged() -> dict[str, dict]:
    """Facts per SHA-1 from everyone's files: the newest measurement wins."""
    out: dict[str, dict] = {}
    for f in sorted(local_dir().glob("*.json")) if local_dir().exists() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key, facts in (d.get("pdfs") or {}).items():
            if isinstance(facts, dict) and facts.get("at", "") > out.get(key, {}).get("at", ""):
                out[key] = facts | {"by": d.get("operator")}
    return out


def sync(pd, cfg) -> dict[str, dict]:
    from . import board

    board.sync(pd, cfg, SUB)
    return merged()


def publish(pd, cfg, mine: dict) -> str:
    from . import board

    if mine.get("pdfs") is not None and (local_dir() / board.file_name(mine["operator"])).exists() is False:
        save_mine(mine)
    return board.publish_file(pd, cfg, local_dir() / board.file_name(mine["operator"]), SUB)


# ---- running it ----------------------------------------------------------------------------

def record(mine: dict, sha1: str, pdf: Path, reader: "_Reader | None" = None) -> dict:
    """Measure one PDF and save the facts; with a reader, also grade an OCR layer."""
    facts = summarize(pdf)
    if reader is not None and facts.get("layer") == "ocr" and facts["verdict"] in ("text", "mixed") \
            and not garbled(facts.get("screen")):
        facts["quality"] = quality(pdf, facts, reader.get())
    put(mine["operator"], sha1, facts)
    mine["pdfs"][sha1] = facts
    return facts


class _LazyReader:
    """Starts Surya only when the first OCR layer turns up."""

    def __init__(self):
        self.r = None

    def get(self) -> "_Reader":
        if self.r is None:
            self.r = _Reader()
        return self.r

    def close(self):
        if self.r:
            self.r.close()


def run(limit: int | None = None, folder: str | None = None, max_mb: float | None = None, share: bool = True,
        redo: bool = False, grade_layers: bool = True, log=print) -> dict:
    """Inventory catalog PDFs nobody has measured yet: download one at a time, measure, delete.

    Resumable: what's done is saved after every PDF. Books already on this machine aren't downloaded."""
    from . import board, book, library
    from .catalog import load_works

    pd, cfg = book._proton()
    if not cfg.operator:
        raise SystemExit('set your name first: `amocr init --operator "<your Proton username>"`')
    known = sync(pd, cfg) if share else merged()
    mine = load_mine(cfg.operator)
    cat = library.load()
    root = cat.get("root", cfg.proton_root).rstrip("/")
    here = {board.sha1_of(w): w for w in load_works().values() if w.source.exists()}
    todo = [e for e in cat.get("entries", []) if e.get("state") != "gone" and e.get("sha1")
            and (redo or e["sha1"] not in known or known[e["sha1"]].get("v") != VERSION)
            and (not folder or library.split_path(e["path"])[0] == folder)
            and (max_mb is None or (e.get("size") or 0) <= max_mb * 1048576)]
    todo.sort(key=lambda e: e.get("size") or 0)  # small first: the most books soonest
    if limit:
        todo = todo[:limit]
    done = failed = 0
    started = time.time()
    lazy = _LazyReader() if grade_layers else None
    try:
        return _run_loop(todo, here, root, pd, cfg, mine, lazy, share, log, started)
    finally:
        if lazy:
            lazy.close()


def _run_loop(todo, here, root, pd, cfg, mine, lazy, share, log, started) -> dict:
    done = failed = 0
    for i, e in enumerate(todo, 1):
        try:
            if e["sha1"] in here:
                facts = record(mine, e["sha1"], here[e["sha1"]].source, lazy)
            else:
                with tempfile.TemporaryDirectory(dir=data_dir()) as td:
                    pd.download(f"{root}/{e['path']}", Path(td))
                    got = Path(td) / e["name"]
                    if not got.exists():
                        pdfs = list(Path(td).glob("*.pdf"))
                        if len(pdfs) != 1:
                            raise RuntimeError("the download produced no PDF")
                        got = pdfs[0]
                    facts = record(mine, e["sha1"], got, lazy)
            done += 1
            log(f"[{i}/{len(todo)}] {(short(facts) or {}).get('label', '')[:44]:<44} {facts.get('script') or '-':<12} "
                f"{facts['pages']:>4} pp  {e['path']}" + (f"  ({facts['why']})" if facts.get("why") else ""))
        except Exception as ex:  # noqa: BLE001 - one bad PDF mustn't stop the run
            failed += 1
            put(mine["operator"], e["sha1"], {"v": VERSION, "at": _now(), "error": str(ex)[:300]})
            log(f"[{i}/{len(todo)}] FAILED {e['path']}: {ex}")
        if share and done and done % 25 == 0:
            publish(pd, cfg, load_mine(cfg.operator))
    shared = publish(pd, cfg, load_mine(cfg.operator)) if share else "not shared: --local"
    return {"done": done, "failed": failed, "todo": len(todo), "minutes": round((time.time() - started) / 60, 1),
            "shared": shared}


# ---- how good is an existing OCR layer? -----------------------------------------------------

PUNCT = "\"'“”‘’()[]{}<>.,;:!?।॥|-–—_/\\*#@%&+=~^`0123456789०१२३४५६७८९"


def _tokens(text: str) -> list[str]:
    out = []
    for t in unicodedata.normalize("NFC", text).split():
        t = t.strip(PUNCT)
        if len(t) >= 2:
            out.append(t.lower())
    return out


def compare(layer: str, fresh: str) -> dict:
    """Word-level agreement of an existing text layer with a fresh reading, in any order
    (OCR layers often put headers, columns and footnotes in a different order)."""
    a, b = Counter(_tokens(layer)), Counter(_tokens(fresh))
    hit = sum((a & b).values())
    na, nb = sum(a.values()), sum(b.values())
    marks = lambda t: sum(c in IAST_MARKS for c in unicodedata.normalize("NFC", t))
    ma, mb = marks(layer), marks(fresh)
    return {"layer_words": na, "fresh_words": nb,
            "precision": round(hit / na, 3) if na else None,  # layer words the fresh reading confirms
            "recall": round(hit / nb, 3) if nb else None,  # fresh words the layer has
            "diacritics_kept": round(min(ma / mb, 1.0), 2) if mb >= 20 else None}


def grade(q: dict) -> str:
    p, r, d = q.get("precision"), q.get("recall"), q.get("diacritics_kept")
    if p is None or r is None:
        return "unknown"
    if p >= 0.9 and r >= 0.85 and (d is None or d >= 0.8):
        return "good"
    if p < 0.75 or r < 0.6 or (d is not None and d < 0.5):
        return "poor"
    return "fair"


class _Reader:
    """Surya when installed (any script), else Tesseract (whose IAST is weak)."""

    def __init__(self):
        self.surya = None
        try:
            from .engines.surya import Surya

            self.surya = Surya(split_with_tesseract=False)
        except SystemExit:
            pass

    @property
    def name(self) -> str:
        return "surya" if self.surya else "tesseract"

    def read(self, img: Path, script: str | None) -> str:
        if self.surya:
            return self.surya.run(img).text
        from .engines.tesseract import Tesseract

        langs = "san+hin" if script == "Devanagari" else "eng"
        return Tesseract(langs=langs).run(img).text

    def close(self):
        if self.surya:
            self.surya.close()


def quality(pdf: Path, facts: dict, reader: _Reader, pages: int = 3) -> dict:
    """Read a few OCR-layer pages afresh and compare them with the existing text."""
    import pymupdf

    t0 = time.time()
    doc = pymupdf.open(pdf)
    lp = facts.get("layer_pages") or []
    picks = sorted({lp[int(len(lp) * f)] for f in (0.25, 0.5, 0.75)})[:pages] if lp else []
    layer_txt, fresh_txt, per_page = [], [], []
    with tempfile.TemporaryDirectory(dir=data_dir()) as td:
        for p in picks:
            page = doc[p - 1]
            img = Path(td) / f"p{p}.png"
            page.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY).save(img)
            lt, ft = page.get_text(), reader.read(img, facts.get("script"))
            layer_txt.append(lt)
            fresh_txt.append(ft)
            per_page.append({"page": p} | compare(lt, ft))
    q = compare("\n".join(layer_txt), "\n".join(fresh_txt)) if picks else {}
    q |= {"engine": reader.name, "pages": per_page, "at": _now(), "seconds": round(time.time() - t0, 1)}
    q["grade"] = grade(q)
    return q


def run_quality(limit: int | None = None, share: bool = True, redo: bool = False, log=print) -> dict:
    """For every PDF whose usable text may be someone's OCR: find out, and if so grade it."""
    from . import board, book, library
    from .catalog import load_works

    pd, cfg = book._proton()
    if not cfg.operator:
        raise SystemExit('set your name first: `amocr init --operator "<your Proton username>"`')
    facts = sync(pd, cfg) if share else merged()
    cat = library.load()
    root = cat.get("root", cfg.proton_root).rstrip("/")
    here = {board.sha1_of(w): w for w in load_works().values() if w.source.exists()}

    def candidate(f: dict) -> bool:
        if f.get("verdict") not in ("text", "mixed"):
            return False
        if "layer" not in f:  # measured before OCR layers were told apart
            return bool(f.get("scans"))
        return f.get("layer") == "ocr" and (redo or not f.get("quality"))

    todo = [e for e in cat.get("entries", []) if e.get("state") != "gone" and candidate(facts.get(e.get("sha1") or "", {}))]
    todo.sort(key=lambda e: e.get("size") or 0)
    if limit:
        todo = todo[:limit]
    reader = _Reader()
    graded = Counter()
    try:
        for i, e in enumerate(todo, 1):
            key = e["sha1"]
            try:
                with tempfile.TemporaryDirectory(dir=data_dir()) as td:
                    if key in here:
                        pdf = here[key].source
                    else:
                        pd.download(f"{root}/{e['path']}", Path(td))
                        pdf = Path(td) / e["name"]
                    f = facts.get(key, {})
                    if "layer" not in f:
                        f = summarize(pdf)
                    if f.get("layer") == "ocr":
                        f["quality"] = quality(pdf, f, reader)
                        g = f["quality"]["grade"]
                    else:
                        g = "born-digital"
                    put(cfg.operator, key, f)
                graded[g] += 1
                q = f.get("quality") or {}
                log(f"[{i}/{len(todo)}] {g:<12} words confirmed {q.get('precision', '-')!s:<5} found {q.get('recall', '-')!s:<5} "
                    f"diacritics {q.get('diacritics_kept', '-')!s:<4} {e['path']}")
            except Exception as ex:  # noqa: BLE001
                graded["failed"] += 1
                log(f"[{i}/{len(todo)}] FAILED {e['path']}: {ex}")
    finally:
        reader.close()
    shared = publish(pd, cfg, load_mine(cfg.operator)) if share else "not shared: --local"
    return {"todo": len(todo), **graded, "engine": reader.name, "shared": shared}


def effective(facts: dict) -> str:
    """The verdict, with OCR layers judged by their quality: a poor or unchecked layer needs OCR."""
    v = facts.get("verdict", "unknown")
    if facts.get("error"):
        return "error"
    if v in ("text", "mixed") and garbled(facts.get("screen")):
        return "garbled"
    if v in ("text", "mixed") and facts.get("layer") == "ocr":
        g = (facts.get("quality") or {}).get("grade")
        return {"good": v, "fair": "layer-fair", "poor": "layer-poor"}.get(g, "layer-unchecked")
    return v


def stats(cat: dict, facts: dict[str, dict]) -> dict:
    live = [e for e in cat.get("entries", []) if e.get("state") != "gone"]
    c = Counter(effective(facts[e["sha1"]]) if e.get("sha1") in facts else "unknown" for e in live)
    return {"pdfs": len(live), **c}


def short(facts: dict | None) -> dict | None:
    """What the Library page shows."""
    if not facts:
        return None
    if facts.get("error"):
        return {"verdict": "error", "label": "couldn't check", "error": facts["error"]}
    v = effective(facts)
    q = facts.get("quality") or {}
    label = VERDICTS.get(facts["verdict"], facts["verdict"])
    sc = facts.get("screen") or {}
    if v == "garbled":
        label = "text layer garbled" + (f" ({round(100 * sc['deva_broken'], 1)}% broken Devanagari)" if (sc.get("deva_broken") or 0) >= GARBLED_DEVA
                                        else f" ({round(100 * sc['odd_letters'], 1)}% legacy-font letters)")
    elif facts.get("layer") == "ocr":
        pct = f" ({round(100 * q['precision'])}% of words confirmed)" if q.get("precision") is not None else ""
        label = {"layer-poor": "OCR layer, poor", "layer-fair": "OCR layer, fair", "layer-unchecked": "OCR layer, not checked"
                 }.get(v, "OCR layer, good") + pct
    elif facts.get("layer") == "digital":
        label += " (born-digital)"
    return {"verdict": v, "label": label, "script": facts.get("script"), "why": facts.get("why"),
            "pages": facts.get("pages"), "kinds": facts.get("kinds"), "producer": facts.get("producer"),
            "diacritics_kept": q.get("diacritics_kept"), "screen": facts.get("screen")}
