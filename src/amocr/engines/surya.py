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


def place_lines(texts: list[str], block_box: list[float], tess_lines: list[dict]) -> list[tuple[str, list[float]]]:
    """Pair a block's lines with Tesseract line boxes inside it; re-split a re-flowed paragraph."""
    inside = sorted((t for t in tess_lines if _inside(t["bbox"], block_box)), key=lambda t: (t["bbox"][1], t["bbox"][0]))
    if len(texts) == 1 and len(inside) > 1:
        texts = split_like(texts[0], [t["text"] for t in inside])
    if len(texts) == len(inside):
        return [(t, b["bbox"]) for t, b in zip(texts, inside) if t]
    box = [round(v) for v in block_box]
    return [(t, box) for t in texts if t]


class Surya(Engine):
    name = "surya"

    def __init__(self, split_with_tesseract: bool = True):
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
            self._tess = Tesseract() if shutil.which("tesseract") else None

    @cache
    def version(self) -> str:
        from importlib.metadata import version

        return version("surya-ocr")

    def config(self) -> dict:
        return {"model": MODEL, "mode": "full_page", "lines": "split along tesseract line boxes" if self._tess else "as returned",
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
            for text, box in place_lines(html_to_lines(b.html or ""), list(b.bbox), tess_lines):
                lines.append({"text": text, "conf": conf, "bbox": [round(v) for v in box], "block": n, "par": 1, "label": b.label})
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
