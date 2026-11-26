"""Surya 2.5 (Datalab), a local OCR model with Devanagari support. Optional: `uv sync --extra surya`.

Surya reads the whole page in one call and returns blocks (header, text, footnote ...) in reading
order. Verse blocks keep their printed line breaks; prose paragraphs come back re-flowed as one
line. The proofreading conventions want one printed line per line, and the viewer needs a box on
the scan per line, so each block is split again along Tesseract's line boxes inside that block.

Licence: the code is Apache-2.0, but the model weights use a modified AI Pubs Open RAIL-M licence
(attribution, share-alike on Output, limits above $5M revenue/funding). See docs/engines.md.
"""

from __future__ import annotations

import html as htmllib
import re
import time
from functools import cache
from pathlib import Path

from .base import Engine, OcrResult

MODEL = "surya-ocr-2.5"
SKIP_LABELS = {"Picture", "Figure", "Diagram"}


def html_to_lines(h: str) -> list[str]:
    """Surya block HTML to printed lines: <br/> breaks lines, <sup>३</sup> becomes a plain marker."""
    h = re.sub(r"<sup>\s*(.*?)\s*</sup>", r"\1", h, flags=re.S)
    h = re.sub(r"<br\s*/?>|</p>\s*<p[^>]*>|</li>\s*<li[^>]*>", "\n", h)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", h))
    return [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.split("\n") if ln.strip()]


def split_like(text: str, targets: list[str]) -> list[str]:
    """Split one re-flowed paragraph into len(targets) lines, breaking where the targets break.

    The two readings are aligned character by character (Levenshtein), each target line end
    is mapped into `text` and snapped to the nearest space. Misread characters in either
    reading barely move a break, unlike splitting by length.
    """
    words = text.split()
    if len(targets) <= 1 or not words:
        return [text] if text else []
    from rapidfuzz.distance import Levenshtein

    text = " ".join(words)
    joined = "\n".join(targets)
    ends = [i for i, ch in enumerate(joined) if ch == "\n"]
    ops = Levenshtein.opcodes(joined, text)

    def mapped(p: int) -> int:
        for op in ops:
            if op.src_start <= p < op.src_end:
                if op.tag == "equal":
                    return op.dest_start + (p - op.src_start)
                span = max(1, op.src_end - op.src_start)
                return op.dest_start + round((p - op.src_start) * (op.dest_end - op.dest_start) / span)
        return len(text)

    spaces = [i for i, ch in enumerate(text) if ch == " "]
    cuts, last = [], -1
    for e in ends:
        m = mapped(e)
        options = [s for s in spaces if s > last] or [len(text)]
        c = min(options, key=lambda s: abs(s - m))
        cuts.append(c)
        last = c
    out, start = [], 0
    for c in cuts:
        out.append(text[start:c].strip())
        start = c + 1
    out.append(text[start:].strip())
    return out


def split_by_length(text: str, targets: list[str]) -> list[str]:
    """Fallback split in proportion to the targets' lengths (each word goes where its midpoint falls)."""
    words = text.split()
    if len(targets) <= 1 or not words:
        return [text] if text else []
    weights = [max(1, len(t.replace(" ", ""))) for t in targets]
    total_t, total_s = sum(weights), sum(len(w) for w in words)
    bounds, acc = [], 0
    for w in weights:
        acc += w
        bounds.append(acc / total_t)
    out: list[list[str]] = [[] for _ in targets]
    done, i = 0, 0
    for w in words:
        mid = (done + len(w) / 2) / total_s
        while i < len(bounds) - 1 and mid > bounds[i]:
            i += 1
        out[i].append(w)
        done += len(w)
    return [" ".join(x) for x in out]


def _inside(line_box: list[float], block_box: list[float], margin: float = 8) -> bool:
    cx, cy = (line_box[0] + line_box[2]) / 2, (line_box[1] + line_box[3]) / 2
    return block_box[0] - margin <= cx <= block_box[2] + margin and block_box[1] - margin <= cy <= block_box[3] + margin


def _union(boxes: list[list[float]]) -> list[int]:
    return [round(min(b[0] for b in boxes)), round(min(b[1] for b in boxes)), round(max(b[2] for b in boxes)), round(max(b[3] for b in boxes))]


def sub_lines(block_box: list[float], tess_lines: list[dict]) -> list[dict]:
    """Tesseract's lines restricted to the words inside this block (a Tesseract line that
    runs across two Surya blocks, like a page number and a running title, is cut in two)."""
    out = []
    for t in tess_lines:
        words = [w for w in t.get("words") or [] if _inside(w["bbox"], block_box)]
        if not t.get("words") and _inside(t["bbox"], block_box):  # results saved before word boxes were kept
            words = [{"text": t["text"], "bbox": t["bbox"]}]
        if words:
            out.append({"text": " ".join(w["text"] for w in words), "bbox": _union([w["bbox"] for w in words]), "words": words})
    return sorted(out, key=lambda t: (t["bbox"][1], t["bbox"][0]))


def _even_slices(box: list[float], n: int) -> list[list[int]]:
    h = (box[3] - box[1]) / max(1, n)
    return [[round(box[0]), round(box[1] + i * h), round(box[2]), round(box[1] + (i + 1) * h)] for i in range(n)]


def word_boxes(text: str, line_box: list[int], tess_words: list[dict]) -> list[dict]:
    """A box for every word of `text`: from the Tesseract words its characters align with,
    else by its position along the line."""
    words = text.split()
    if not words:
        return []
    spans, pos = [], 0
    for w in words:
        i = text.find(w, pos)
        spans.append((i, i + len(w)))
        pos = i + len(w)

    def estimate(i0: int, i1: int) -> list[int]:
        x0, x1 = line_box[0], line_box[2]
        n = max(1, len(text))
        return [round(x0 + (x1 - x0) * i0 / n), line_box[1], round(x0 + (x1 - x0) * i1 / n), line_box[3]]

    if not tess_words:
        return [{"text": w, "bbox": estimate(a, b), "box": "estimated"} for w, (a, b) in zip(words, spans)]
    from rapidfuzz.distance import Levenshtein

    tess_words = sorted(tess_words, key=lambda w: w["bbox"][0])
    joined, owner = "", []
    for k, w in enumerate(tess_words):
        if joined:
            joined += " "
            owner.append(None)
        joined += w["text"]
        owner += [k] * len(w["text"])
    ops = Levenshtein.opcodes(text, joined)

    def to_tess(p: int) -> int | None:
        for op in ops:
            if op.src_start <= p < op.src_end and op.dest_end > op.dest_start:
                q = op.dest_start + (p - op.src_start if op.tag == "equal" else
                                     round((p - op.src_start) * (op.dest_end - op.dest_start) / max(1, op.src_end - op.src_start)))
                q = min(q, len(owner) - 1)
                for d in range(len(owner)):  # nearest character that belongs to a word
                    for c in (q - d, q + d):
                        if 0 <= c < len(owner) and owner[c] is not None:
                            return owner[c]
        return None

    out = []
    for w, (a, b) in zip(words, spans):
        hits = {k for k in (to_tess(p) for p in range(a, b)) if k is not None}
        if hits:
            out.append({"text": w, "bbox": _union([tess_words[k]["bbox"] for k in hits]), "box": "tesseract"})
        else:
            out.append({"text": w, "bbox": estimate(a, b), "box": "estimated"})
    return out


def place_lines(texts: list[str], block_box: list[float], tess_lines: list[dict]) -> list[dict]:
    """One entry per printed line of the block, each with its own line box and word boxes."""
    subs = sub_lines(block_box, tess_lines)
    if len(texts) == 1 and len(subs) > 1:
        texts = split_like(texts[0], [t["text"] for t in subs])
    if len(texts) == len(subs):
        pairs = [(t, sub["bbox"], sub["words"], "tesseract") for t, sub in zip(texts, subs)]
    else:  # can't match Tesseract's lines: share the block out evenly, top to bottom
        pairs = [(t, box, [w for w in (x for s in subs for x in s["words"]) if _inside(w["bbox"], box, 0)], "estimated")
                 for t, box in zip(texts, _even_slices(block_box, len(texts)))]
    return [{"text": t, "bbox": [round(v) for v in box], "box": how, "words": word_boxes(t, [round(v) for v in box], tw)}
            for t, box, tw, how in pairs if t]


DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
VERSE_END = re.compile(r"॥\s*([०-९0-9]+(?:\s*[-–]\s*[०-९0-9]+)?[^॥]{0,3})\s*॥\s*$")
LINE_END = re.compile(r"(।|॥\s*[०-९0-9][^॥]{0,8}॥)\s*$")
LABEL_TYPES = {"PageHeader": "header", "Footnote": "footnote", "PageFooter": "signature", "Caption": "other",
               "Picture": "other", "Table": "other"}


def _num(s: str) -> str:
    return re.sub(r"\s+", "", s.translate(DIGITS))


FOOTNOTE = re.compile(r"^\s*[०-९0-9]+\s*[.,]\s")
SIGNATURE = re.compile(r"^\s*\S{1,3}०\s*\S{1,3}०\s*[—–-]+\s*[०-९0-9]+\s*$")
HINDI = {"है", "हैं", "के", "की", "का", "में", "से", "को", "और", "यह", "वह", "भी", "हो", "जाता", "जाती", "करना", "कि,"}


def classify(label: str, lines: list[str]) -> list[dict]:
    """Structure for one block: its type, and for each line the verse it belongs to (verse)
    or the verses the block explains (commentary)."""
    if label in LABEL_TYPES:
        return [{"type": LABEL_TYPES[label]} for _ in lines]
    if lines and all(SIGNATURE.match(ln) for ln in lines):
        return [{"type": "signature"} for _ in lines]
    if lines and FOOTNOTE.match(lines[0]):
        return [{"type": "footnote"} for _ in lines]
    ended = sum(1 for ln in lines if LINE_END.search(ln))
    hindi = sum(1 for ln in lines for w in ln.split() if w in HINDI)  # Hindi function words: commentary, never verse
    if lines and ended / len(lines) >= 0.6 and hindi < len(lines):
        out, pending = [], []
        for ln in lines:
            pending.append({"type": "verse"})
            m = VERSE_END.search(ln)
            if m:
                for x in pending:
                    x["verse"] = _num(m.group(1))
                out += pending
                pending = []
        return out + pending  # a half-verse at the end of the block continues on the next page
    explains = None
    for ln in reversed(lines):
        m = VERSE_END.search(ln)
        if m:
            explains = _num(m.group(1))
            break
    return [{"type": "commentary"} | ({"explains": explains} if explains else {}) for _ in lines]


class Surya(Engine):
    name = "surya"

    def __init__(self, split_with_tesseract: bool = True, tesseract_langs: str = "san+hin"):
        try:
            import surya  # noqa: F401
        except ImportError:
            raise SystemExit("Surya is not installed. Run `uv sync --extra surya` (it also needs llama-server: "
                             "it comes with Ollama, or `brew install llama.cpp`). See docs/engines.md.") from None
        self._manager = None
        self._predictor = None
        self._tess = None
        if split_with_tesseract:
            import shutil

            from .tesseract import Tesseract
            # the book's languages (amocr.languages): its lines are placed with Tesseract's boxes
            self._tess = Tesseract(langs=tesseract_langs) if shutil.which("tesseract") else None

    @cache
    def version(self) -> str:
        from importlib.metadata import version

        return version("surya-ocr")

    def config(self) -> dict:
        return {"model": MODEL, "mode": "full_page", "positions": "line and word boxes from tesseract words, else estimated" if self._tess else "block boxes only",
                "weights_license": "modified AI Pubs Open RAIL-M (Datalab)"}

    @property
    def label(self) -> str:
        return "surya-2.5"

    def _predict(self, image: Path):
        if self._predictor is None:
            from surya import RecognitionPredictor, SuryaInferenceManager

            self._manager = SuryaInferenceManager()
            self._predictor = RecognitionPredictor(self._manager)
            self._predictor.disable_tqdm = True
        from PIL import Image

        with Image.open(image) as im:
            return self._predictor([im.convert("RGB")])[0]

    def run(self, image: Path) -> OcrResult:
        t0 = time.monotonic()
        page = self._predict(image)
        tess_lines = self._tess.run(image).lines if self._tess else []
        lines, confs = [], []
        blocks = sorted((b for b in page.blocks if b.label not in SKIP_LABELS and not getattr(b, "skipped", False)),
                        key=lambda b: b.reading_order)
        for n, b in enumerate(blocks, 1):
            conf = round(100 * b.confidence, 2) if b.confidence is not None else None
            if conf is not None:
                confs.append(conf)
            placed = place_lines(html_to_lines(b.html or ""), list(b.bbox), tess_lines)
            for ln, meta in zip(placed, classify(b.label, [x["text"] for x in placed])):
                lines.append(ln | meta | {"conf": conf, "block": n, "par": 1, "label": b.label})
        from .tesseract import lines_to_text

        return OcrResult(
            text=lines_to_text(lines) if lines else "\n",
            confidence=round(sum(confs) / len(confs), 2) if confs else None,
            engine=self.name,
            engine_version=self.version(),
            config=self.config(),
            lines=lines,
            seconds=round(time.monotonic() - t0, 2),
        )

    def close(self) -> None:
        if self._manager is not None:
            self._manager.stop()
            self._manager = self._predictor = None
