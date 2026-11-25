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
from .textcheck import classify

VERSION = "inv1"
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
    fonts: Counter = Counter()  # fonts of pages whose text layer isn't usable (legacy encodings)
    need = []  # pages that need OCR, for script detection
    for i, page in enumerate(doc, start=1):
        k = page_kind(page.get_text())
        kinds[k] += 1
        scans += bool(page.get_images())
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
    text_script = max(("devanagari", "iast", "latin"), key=lambda k: kinds[k]) if usable else None
    return {
        "v": VERSION, "at": _now(), "pages": n, "scans": scans,
        "kinds": {k: kinds[k] for k in ("devanagari", "iast", "latin", "suspect", "none") if kinds[k]},
        "verdict": verdict, "why": why, "fonts": [n for n, _ in fonts.most_common(3)] or None,
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

    save_mine(mine)
    return board.publish_file(pd, cfg, local_dir() / board.file_name(mine["operator"]), SUB)


# ---- running it ----------------------------------------------------------------------------

def record(mine: dict, sha1: str, pdf: Path) -> dict:
    facts = summarize(pdf)
    mine["pdfs"][sha1] = facts
    save_mine(mine)
    return facts


def run(limit: int | None = None, folder: str | None = None, max_mb: float | None = None, share: bool = True,
        redo: bool = False, log=print) -> dict:
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
    for i, e in enumerate(todo, 1):
        try:
            if e["sha1"] in here:
                facts = record(mine, e["sha1"], here[e["sha1"]].source)
            else:
                with tempfile.TemporaryDirectory(dir=data_dir()) as td:
                    pd.download(f"{root}/{e['path']}", Path(td))
                    got = Path(td) / e["name"]
                    if not got.exists():
                        pdfs = list(Path(td).glob("*.pdf"))
                        if len(pdfs) != 1:
                            raise RuntimeError("the download produced no PDF")
                        got = pdfs[0]
                    facts = record(mine, e["sha1"], got)
            done += 1
            log(f"[{i}/{len(todo)}] {VERDICTS[facts['verdict']]:<26} {facts.get('script') or '-':<12} "
                f"{facts['pages']:>4} pp  {e['path']}" + (f"  ({facts['why']})" if facts.get("why") else ""))
        except Exception as ex:  # noqa: BLE001 - one bad PDF mustn't stop the run
            failed += 1
            mine["pdfs"][e["sha1"]] = {"v": VERSION, "at": _now(), "error": str(ex)[:300]}
            save_mine(mine)
            log(f"[{i}/{len(todo)}] FAILED {e['path']}: {ex}")
        if share and done and done % 25 == 0:
            publish(pd, cfg, mine)
    shared = publish(pd, cfg, mine) if share else "not shared: --local"
    return {"done": done, "failed": failed, "todo": len(todo), "minutes": round((time.time() - started) / 60, 1),
            "shared": shared}


def stats(cat: dict, facts: dict[str, dict]) -> dict:
    live = [e for e in cat.get("entries", []) if e.get("state") != "gone"]
    c = Counter(facts.get(e.get("sha1") or "", {}).get("verdict", "unknown") for e in live)
    return {"pdfs": len(live), **c}


def short(facts: dict | None) -> dict | None:
    """What the Library page shows."""
    if not facts:
        return None
    if facts.get("error"):
        return {"verdict": "error", "label": "couldn't check", "error": facts["error"]}
    return {"verdict": facts["verdict"], "label": VERDICTS[facts["verdict"]], "script": facts.get("script"), "why": facts.get("why"),
            "pages": facts.get("pages"), "kinds": facts.get("kinds")}

