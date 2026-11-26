"""Claude as an OCR engine, run inside a Claude Code session on the Pro plan.

There is no API call. `prep` writes a packet per page (image bands sized for
reading, plus the Tesseract text); Claude reads the packet in-session and
writes result.json; `import_result` validates it and stores it like any other
engine result, so `amocr eval` scores it the same way.

result.json schema:
{
  "work": "SL-0001", "page": 231, "mode": "direct" | "correct",   # "review": see claude_review.py
  "model": "claude-opus-5-5",
  "regions": [
    {"type": "header|verse|commentary|footnote|signature|other",
     "verse": "34" | null,          # verse number the region ends with or explains
     "lines": ["one printed line per entry", ...]}
  ],
  "changes": [{"from": "...", "to": "...", "why": "..."}],   # correct mode only
  "uncertain": ["text Claude could not read with confidence", ...]
}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import __version__
from .catalog import Work

REGION_TYPES = {"header", "verse", "commentary", "footnote", "signature", "other"}
MODES = {"direct", "correct", "review", "screen"}
BANDS = [(0.0, 0.38), (0.30, 0.68), (0.60, 1.0)]  # overlapping, so no line is cut in every band
BASELINE = "tesseract-san+hin-psm3"


def inbox(work: Work, page: int) -> Path:
    return work.workdir / "claude" / f"p{page:04d}"


def prep(work: Work, page: int, image: Path, mode: str = "bands") -> Path:
    """mode "bands": whole-page strips + Tesseract text. mode "review": numbered line images + Surya's text."""
    d = inbox(work, page)
    if mode == "review":
        from .claude_review import prep_review

        return prep_review(work, page, image, d)
    if mode == "screen":
        from .claude_review import prep_screen

        return prep_screen(work, page, d)
    d.mkdir(parents=True, exist_ok=True)
    for old in list(d.glob("sheet*.png")) + [d / "review.txt", d / "lines.json"]:
        old.unlink(missing_ok=True)
    im = Image.open(image)
    w, h = im.size
    for i, (a, b) in enumerate(BANDS):
        im.crop((0, int(h * a), w, int(h * b))).save(d / f"band{i}.png")
    from .languages import tesseract_langs

    ocr = work.page_dir(page) / "ocr"   # the book's own models first (san+hin, or eng ...), else any Tesseract reading
    base = sorted(ocr.glob(f"tesseract-{tesseract_langs(work)}-psm3-*.txt")) or sorted(ocr.glob(f"{BASELINE}-*.txt")) \
        or sorted(ocr.glob("tesseract-*-psm3-*.txt"))
    if base:
        (d / "tesseract.txt").write_text(base[-1].read_text(encoding="utf-8"), encoding="utf-8")
    return d


def validate(res: dict, work: Work, page: int, baseline_text: str | None) -> list[str]:
    """Hard errors raise; soft problems come back as warnings."""
    if res.get("work") != work.id or res.get("page") != page:
        raise ValueError(f"result is for {res.get('work')} p{res.get('page')}, expected {work.id} p{page}")
    if res.get("mode") not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    regions = res.get("regions") or []
    if not regions:
        raise ValueError("no regions")
    for r in regions:
        if r.get("type") not in REGION_TYPES:
            raise ValueError(f"bad region type {r.get('type')!r}")
        if not isinstance(r.get("lines"), list) or not all(isinstance(x, str) for x in r["lines"]):
            raise ValueError("region lines must be a list of strings")
    warnings = []
    if res["mode"] == "correct" and "changes" not in res:
        warnings.append("correct mode but no changes list")
    if baseline_text:
        # Dropped or merged lines are Claude's most dangerous failure; compare against Tesseract's line count.
        n_claude = sum(len(r["lines"]) for r in regions)
        n_tess = sum(1 for ln in baseline_text.splitlines() if ln.strip())
        if n_claude < n_tess - 2:
            warnings.append(f"possible dropped lines: Claude {n_claude}, Tesseract {n_tess}")
        len_c = sum(len(x) for r in regions for x in r["lines"])
        len_t = len(baseline_text.replace("\n", ""))
        if len_t and len_c / len_t < 0.9:
            warnings.append(f"text {len_c / len_t:.0%} the length of Tesseract's")
    return warnings


def to_text(res: dict) -> str:
    return "\n\n".join("\n".join(r["lines"]) for r in res["regions"]) + "\n"


def _review_record(work: Work, page: int, d: Path, res: dict) -> tuple[str, list[dict], list[dict], list[dict], list[str], dict]:
    from .claude_review import apply_review, regions

    if res.get("work") != work.id or res.get("page") != page:
        raise ValueError(f"result is for {res.get('work')} p{res.get('page')}, expected {work.id} p{page}")
    packet = json.loads((d / "lines.json").read_text(encoding="utf-8"))
    config = {"mode": res["mode"], "base": packet["base"]}
    extra: list[str] = []
    if res["mode"] == "screen":
        from .claude_review import read_flags

        flags = read_flags(d, work, page)
        res = {"block_types": flags.get("block_types", {})} | res
        flagged = {fl["line"] for fl in flags.get("flags", [])}
        by_tess = {i for i, ln in enumerate(packet["lines"], 1) if ln.get("tess")}
        checked = flagged | by_tess
        touched = {c.get("line") for c in res.get("changes", [])} | {x.get("line") for x in res.get("delete", [])}
        if touched - checked:
            extra.append(f"changes to lines that weren't checked against an image: {sorted(touched - checked)}")
        config |= {"flagged_by_claude": sorted(flagged), "flagged_by_tesseract": sorted(by_tess - flagged),
                   "lines": len(packet["lines"])}
    lines, changes, warnings = apply_review(res, packet["lines"])
    regs = regions(lines)
    out_lines = [{k: v for k, v in {"text": ln["text"], "type": ln["type"], "verse": ln.get("verse"), "explains": ln.get("explains"),
                                    "bbox": ln.get("bbox"), "words": ln.get("words")}.items() if v is not None or k in ("text", "type")}
                 for ln in lines]
    return to_text({"regions": regs}), regs, out_lines, changes, warnings + extra, config


def import_result(work: Work, page: int, force: bool = False, operator: str = "") -> tuple[Path, list[str]]:
    d = inbox(work, page)
    res = json.loads((d / "result.json").read_text(encoding="utf-8"))
    if res.get("mode") in ("review", "screen"):
        text, regs, out_lines, changes, warnings, config = _review_record(work, page, d, res)
        return _store(work, page, res, text, regs, out_lines, changes, warnings, config, force, operator)
    base = d / "tesseract.txt"
    warnings = validate(res, work, page, base.read_text(encoding="utf-8") if base.exists() else None)
    lines = [{"text": ln, "type": r["type"], "verse": r.get("verse")} for r in res["regions"] for ln in r["lines"]]
    return _store(work, page, res, to_text(res), res["regions"], lines, res.get("changes", []), warnings,
                  {"mode": res["mode"]}, force, operator)


def _store(work: Work, page: int, res: dict, text: str, regs: list[dict], lines: list[dict], changes: list[dict],
           warnings: list[str], config: dict, force: bool, operator: str) -> tuple[Path, list[str]]:
    label = f"claude-code-{res['mode']}-{res.get('model', 'unknown')}"
    out = work.page_dir(page) / "ocr" / f"{label}.json"
    if out.exists() and not force:
        raise FileExistsError(f"{out.name} exists; use --force to replace")
    rec = {
        "text": text,
        "confidence": None,
        "engine": "claude-code",
        "engine_version": res.get("model", "unknown"),
        "config": config,
        "lines": lines,
        "regions": regs,
        "changes": changes,
        "uncertain": res.get("uncertain", []),
        "warnings": warnings,
        "seconds": 0.0,
        "cost_usd": 0.0,
        "work": work.id,
        "page": page,
        "operator": operator,
        "amocr_version": __version__,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".txt").write_text(text, encoding="utf-8")
    return out, warnings


def has_claude_result(work: Work, page: int) -> bool:
    return any((work.page_dir(page) / "ocr").glob("claude-code-*.json"))


def ready(work: Work) -> list[int]:
    """Pages whose packet has a result.json that is not imported yet."""
    out = []
    for d in sorted((work.workdir / "claude").glob("p*")):
        page = int(d.name[1:])
        if (d / "result.json").exists() and not has_claude_result(work, page):
            out.append(page)
    return out


def next_pages(work: Work, n: int, needs_ocr: list[int]) -> list[int]:
    """The next n pages (in order) without a Claude result."""
    return [p for p in needs_ocr if not has_claude_result(work, p)][:n]
