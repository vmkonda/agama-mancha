"""Claude reviews Surya's reading line by line, instead of re-reading whole pages.

Every Surya line has a box on the scan, so the packet holds only what Claude needs:

  sheet0.png, sheet1.png ...  the page's line images, stacked about 10 per sheet and numbered
  review.txt                  Surya's text with the same numbers (plus Tesseract's reading
                              where the two disagree a lot)
  lines.json                  the base lines with their boxes, used by the import

Claude writes only corrections, which is where the tokens go. result.json:
{
  "work": "B-...", "page": 231, "mode": "review", "model": "claude-opus-5-5",
  "changes": [{"line": 12, "to": "the whole corrected line", "why": "..."}],
  "insert":  [{"after": 12, "text": "a printed line Surya missed", "why": "..."}],   # after: 0 = top
  "delete":  [{"line": 5, "why": "not printed on the page"}],
  "block_types": {"3": "verse", "4": "commentary"},   # optional; review.txt shows block numbers
  "uncertain": ["..."]
}
An empty "changes" list is a valid answer: it means every line was checked and is right.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .catalog import Work
from .metrics import cer, normalize

BASE = "surya-2.5"
MAX_W = 1560        # stay under the usual 1568 px long-edge limit, so line images aren't shrunk
MAX_PIXELS = 1.1e6  # and under ~1.15 MP per image
MARGIN = 70         # left margin for the line number
PAD = 6
TESS_HINT = 0.10    # show Tesseract's reading where it differs from Surya's by more than this
LABEL_TYPES = {"PageHeader": "header", "SectionHeader": "header", "PageFooter": "signature",
               "Footnote": "footnote", "Caption": "other"}
REGION_TYPES = {"header", "verse", "commentary", "footnote", "signature", "other"}


def base_result(work: Work, page: int) -> Path | None:
    found = sorted((work.page_dir(page) / "ocr").glob(f"{BASE}-*.json"))
    return found[-1] if found else None


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def build_sheets(image: Path, lines: list[dict], out_dir: Path, numbers: list[int] | None = None,
                 prefix: str = "sheet") -> list[Path]:
    """Crop each line's box, number it, and stack the crops into sheets that stay readable at full size."""
    numbers = numbers or list(range(1, len(lines) + 1))
    page = Image.open(image).convert("L")
    font = _font(30)
    crops = []
    for n, ln in zip(numbers, lines):
        x0, y0, x1, y1 = ln["bbox"]
        c = page.crop((max(0, x0 - PAD), max(0, y0 - PAD), min(page.width, x1 + PAD), min(page.height, y1 + PAD)))
        if c.width + MARGIN > MAX_W:
            s = (MAX_W - MARGIN) / c.width
            c = c.resize((MAX_W - MARGIN, max(1, round(c.height * s))))
        tile = Image.new("L", (c.width + MARGIN, c.height + 8), 255)
        tile.paste(c, (MARGIN, 4))
        d = ImageDraw.Draw(tile)
        d.text((6, max(0, tile.height // 2 - 16)), str(n), fill=0, font=font)
        d.line([(0, tile.height - 1), (tile.width, tile.height - 1)], fill=170)
        crops.append(tile)
    sheets, cur = [], []

    def flush():
        if not cur:
            return
        w, h = max(t.width for t in cur), sum(t.height for t in cur)
        sheet = Image.new("L", (w, h), 255)
        y = 0
        for t in cur:
            sheet.paste(t, (0, y))
            y += t.height
        p = out_dir / f"{prefix}{len(sheets)}.png"
        sheet.save(p)
        sheets.append(p)
        cur.clear()

    for t in crops:
        w = max([t.width] + [x.width for x in cur])
        if cur and w * (sum(x.height for x in cur) + t.height) > MAX_PIXELS:
            flush()
        cur.append(t)
    flush()
    return sheets


def review_text(page: int, lines: list[dict], tess_by_box: dict, sheets: list[Path]) -> str:
    out = [f"Page {page}: Surya's reading, one numbered line per printed line, as on "
           f"{', '.join(p.name for p in sheets)}.",
           "T: is Tesseract's reading of the same line, shown only where it differs a lot. It is often wrong;",
           "use it as a hint, never as the answer. Check every line against the sheet image.", ""]
    block = None
    for n, ln in enumerate(lines, 1):
        if ln.get("block") != block:
            block = ln.get("block")
            out.append(f"[block {block}: {ln.get('label', '?')}]")
        out.append(f"{n:>3}  {ln['text']}")
        t = tess_by_box.get(tuple(ln["bbox"]))
        if t and cer(normalize(t), normalize(ln["text"]), ignore_space=True) > TESS_HINT:
            out.append(f"     T: {t}")
    return "\n".join(out) + "\n"


def _base_lines(work: Work, page: int) -> tuple[Path, list[dict]]:
    base = base_result(work, page)
    if not base:
        raise FileNotFoundError(f"p{page}: no Surya result; run `amocr ocr {work.id} --engine surya --pages {page}`")
    rec = json.loads(base.read_text(encoding="utf-8"))
    tess = sorted((work.page_dir(page) / "ocr").glob("tesseract-*.json"))
    tess_by_box = {tuple(t["bbox"]): t["text"] for t in json.loads(tess[-1].read_text(encoding="utf-8"))["lines"]} if tess else {}
    lines = []
    for ln in rec["lines"]:
        t = tess_by_box.get(tuple(ln["bbox"]))
        far = bool(t) and cer(normalize(t), normalize(ln["text"]), ignore_space=True) > TESS_HINT
        lines.append({"text": ln["text"], "bbox": ln["bbox"], "block": ln.get("block"), "label": ln.get("label"),
                      "tess": t if far else None})
    return base, lines


def _clear(packet: Path) -> None:
    for pat in ("sheet*.png", "band*.png", "check*.png", "review.txt", "screen.txt", "check.txt", "flags.json"):
        for old in packet.glob(pat):
            old.unlink()


def prep_review(work: Work, page: int, image: Path, packet: Path) -> Path:
    base, lines = _base_lines(work, page)
    packet.mkdir(parents=True, exist_ok=True)
    _clear(packet)
    sheets = build_sheets(image, lines, packet)
    (packet / "lines.json").write_text(json.dumps({"base": base.stem, "lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
    tess_by_box = {tuple(ln["bbox"]): ln["tess"] for ln in lines if ln["tess"]}
    (packet / "review.txt").write_text(review_text(page, lines, tess_by_box, sheets), encoding="utf-8")
    return packet


# ---- screen mode: text first, images only for the lines that need them ----------------

def screen_text(page: int, lines: list[dict]) -> str:
    out = [f"Page {page}: Surya's reading, one numbered line per printed line. You have no image yet.",
           "Flag every line that may be misread: non-words, broken sandhi or compounds, a verse that",
           "doesn't scan, Hindi that doesn't parse, footnote markers that don't match the footnotes,",
           "odd verse numbers. Flag only; never correct from the text. When in doubt, flag.", ""]
    block = None
    for n, ln in enumerate(lines, 1):
        if ln.get("block") != block:
            block = ln.get("block")
            out.append(f"[block {block}: {ln.get('label', '?')}]")
        out.append(f"{n:>3}  {ln['text']}")
    return "\n".join(out) + "\n"


def prep_screen(work: Work, page: int, packet: Path) -> Path:
    base, lines = _base_lines(work, page)
    packet.mkdir(parents=True, exist_ok=True)
    _clear(packet)
    (packet / "lines.json").write_text(json.dumps({"base": base.stem, "lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
    (packet / "screen.txt").write_text(screen_text(page, lines), encoding="utf-8")
    return packet


def read_flags(packet: Path, work: Work, page: int) -> dict:
    f = json.loads((packet / "flags.json").read_text(encoding="utf-8"))
    if f.get("work") != work.id or f.get("page") != page:
        raise ValueError(f"flags.json is for {f.get('work')} p{f.get('page')}, expected {work.id} p{page}")
    n = len(json.loads((packet / "lines.json").read_text(encoding="utf-8"))["lines"])
    for fl in f.get("flags", []):
        if not isinstance(fl.get("line"), int) or not 1 <= fl["line"] <= n:
            raise ValueError(f"p{page}: flag for line {fl.get('line')!r}; lines are 1..{n}")
    return f


def prep_check(work: Work, page: int, image: Path, packet: Path) -> tuple[list[int], list[int]]:
    """Line images for the flagged lines plus those where Tesseract disagrees a lot. Returns (by Claude, by Tesseract)."""
    lines = json.loads((packet / "lines.json").read_text(encoding="utf-8"))["lines"]
    flags = read_flags(packet, work, page)
    by_claude = sorted({fl["line"] for fl in flags.get("flags", [])})
    by_tess = sorted(i for i, ln in enumerate(lines, 1) if ln.get("tess") and i not in by_claude)
    check = sorted(set(by_claude) | set(by_tess))
    for old in packet.glob("check*.png"):
        old.unlink()
    sheets = build_sheets(image, [lines[i - 1] for i in check], packet, numbers=check, prefix="check") if check else []
    why = {fl["line"]: fl.get("why", "") for fl in flags.get("flags", [])}
    out = [f"Page {page}: check these lines against {', '.join(p.name for p in sheets) or '(no images: nothing to check)'}.",
           "Numbers are the page's line numbers, as in screen.txt. Write result.json with mode \"screen\"",
           "and corrections for these lines only. An empty changes list means they are all as printed.", ""]
    for i in check:
        ln = lines[i - 1]
        out.append(f"{i:>3}  {ln['text']}")
        if i in why:
            out.append(f"     flagged: {why[i]}")
        if ln.get("tess"):
            out.append(f"     T: {ln['tess']}")
    (packet / "check.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    return by_claude, by_tess


def apply_review(res: dict, base_lines: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Apply Claude's corrections to the base lines. Returns (lines, changes as from/to/why, warnings)."""
    n = len(base_lines)
    warnings: list[str] = []
    for key in ("changes", "insert", "delete"):
        if not isinstance(res.get(key, []), list):
            raise ValueError(f"{key} must be a list")
    edits: dict[int, dict] = {}
    for c in res.get("changes", []):
        i = c.get("line")
        if not isinstance(i, int) or not 1 <= i <= n:
            raise ValueError(f"change for line {i!r}: lines are 1..{n}")
        if i in edits:
            raise ValueError(f"line {i} changed twice")
        if not isinstance(c.get("to"), str) or not c["to"].strip():
            raise ValueError(f"line {i}: 'to' must be the whole corrected line (use delete to remove a line)")
        edits[i] = c
    deletes = {}
    for dl in res.get("delete", []):
        i = dl.get("line")
        if not isinstance(i, int) or not 1 <= i <= n or i in edits:
            raise ValueError(f"bad delete for line {i!r}")
        deletes[i] = dl
    inserts: dict[int, list[dict]] = {}
    for ins in res.get("insert", []):
        a = ins.get("after")
        if not isinstance(a, int) or not 0 <= a <= n or not isinstance(ins.get("text"), str) or not ins["text"].strip():
            raise ValueError(f"bad insert after {a!r}")
        inserts.setdefault(a, []).append(ins)
    types = {str(k): v for k, v in (res.get("block_types") or {}).items()}
    for k, v in types.items():
        if v not in REGION_TYPES:
            raise ValueError(f"block {k}: type must be one of {sorted(REGION_TYPES)}")

    def typ(ln: dict) -> str:
        return types.get(str(ln.get("block")), LABEL_TYPES.get(ln.get("label") or "", "other"))

    out, changes = [], []

    def add_inserts(after: int, neighbour: dict | None):
        for ins in inserts.get(after, []):
            b = neighbour or {}
            out.append({"text": ins["text"].strip(), "bbox": b.get("bbox"), "block": b.get("block"), "type": typ(b), "inserted": True})
            changes.append({"from": "", "to": ins["text"].strip(), "why": ins.get("why", "missing line")})

    add_inserts(0, base_lines[0] if base_lines else None)
    for i, ln in enumerate(base_lines, 1):
        if i in deletes:
            changes.append({"from": ln["text"], "to": "", "why": deletes[i].get("why", "")})
        else:
            text = ln["text"]
            if i in edits:
                text = edits[i]["to"].strip()
                if text != ln["text"]:
                    changes.append({"from": ln["text"], "to": text, "why": edits[i].get("why", ""), "line": i})
            out.append({"text": text, "bbox": ln.get("bbox"), "block": ln.get("block"), "type": typ(ln)})
        add_inserts(i, ln)
    if n and len(edits) / n > 0.5:
        warnings.append(f"{len(edits)} of {n} lines changed: is the base reading this poor, or was a line misnumbered?")
    if deletes:
        warnings.append(f"{len(deletes)} line(s) deleted: check they really aren't printed")
    return out, changes, warnings


def regions(lines: list[dict]) -> list[dict]:
    """Group consecutive lines of the same block into regions, like the other Claude modes."""
    out: list[dict] = []
    for ln in lines:
        if out and out[-1]["_block"] == ln.get("block") and out[-1]["type"] == ln["type"]:
            out[-1]["lines"].append(ln["text"])
        else:
            out.append({"type": ln["type"], "verse": None, "lines": [ln["text"]], "_block": ln.get("block")})
    for r in out:
        del r["_block"]
    return out
