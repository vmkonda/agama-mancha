from __future__ import annotations

import csv
import io
import shutil
import subprocess
import time
import unicodedata
from functools import cache
from pathlib import Path

from .base import Engine, OcrResult


class Tesseract(Engine):
    name = "tesseract"

    def __init__(self, langs: str = "san+hin", psm: int = 3, oem: int = 1):
        from ..setup import MODELS_LABEL, models_present, tessdata_dir

        if not shutil.which("tesseract"):
            raise SystemExit("tesseract not found; see docs/volunteer-guide.md (or ask Claude: \"set me up\")")
        self.langs, self.psm, self.oem = langs, psm, oem
        # Prefer the pinned models from `amocr setup-models` so every volunteer reads with identical files.
        self.tessdata = tessdata_dir() if models_present(langs.split("+")) else None
        self.models = MODELS_LABEL if self.tessdata else "system"

    @cache
    def version(self) -> str:
        out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        return out.splitlines()[0].split()[-1] if out else "unknown"

    def config(self) -> dict:
        return {"langs": self.langs, "psm": self.psm, "oem": self.oem, "models": self.models}

    @property
    def label(self) -> str:
        return f"tesseract-{self.langs}-psm{self.psm}"

    def run(self, image: Path) -> OcrResult:
        t0 = time.monotonic()
        tsv = subprocess.run(
            ["tesseract", str(image), "stdout", "-l", self.langs, "--psm", str(self.psm), "--oem", str(self.oem),
             *(["--tessdata-dir", str(self.tessdata)] if self.tessdata else []),
             # Not the "tsv" config file: Tesseract looks for it under --tessdata-dir, the pinned
             # model folder has no configs/, and it then silently falls back to plain text.
             "-c", "tessedit_create_tsv=1"],
            capture_output=True,
            text=True,
            encoding="utf-8",  # Tesseract writes UTF-8; Windows' default code page would garble Devanagari
            check=True,
        ).stdout
        lines = parse_tsv(tsv)
        text = lines_to_text(lines)
        confs = [w for ln in lines for w in ln["word_confs"]]
        return OcrResult(
            text=text,
            confidence=round(sum(confs) / len(confs), 2) if confs else None,
            engine=self.name,
            engine_version=self.version(),
            config=self.config(),
            lines=[{k: ln[k] for k in ("text", "conf", "bbox", "block", "par", "words")} for ln in lines],
            seconds=round(time.monotonic() - t0, 2),
        )


def parse_tsv(tsv: str) -> list[dict]:
    """Group Tesseract word rows into lines, keeping block/paragraph structure."""
    if tsv.strip() and not tsv.startswith("level\t"):
        # Plain text instead of TSV would otherwise parse as "no words" on every page.
        raise RuntimeError("tesseract did not return TSV output: " + tsv[:80].replace("\n", " "))
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    lines: dict[tuple, dict] = {}
    for r in reader:
        if r.get("level") != "5":
            continue
        word = (r.get("text") or "").strip()
        conf = float(r["conf"])
        if not word or conf < 0:
            continue
        key = (int(r["block_num"]), int(r["par_num"]), int(r["line_num"]))
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        ln = lines.setdefault(key, {"block": key[0], "par": key[1], "words": [], "word_confs": [], "word_boxes": [],
                                    "box": [x, y, x + w, y + h]})
        ln["words"].append(word)
        ln["word_confs"].append(conf)
        ln["word_boxes"].append({"text": unicodedata.normalize("NFC", word), "conf": conf, "bbox": [x, y, x + w, y + h]})
        b = ln["box"]
        ln["box"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
    out = []
    for key in sorted(lines):
        ln = lines[key]
        out.append(
            {
                "block": ln["block"],
                "par": ln["par"],
                "text": unicodedata.normalize("NFC", " ".join(ln["words"])),
                "conf": round(sum(ln["word_confs"]) / len(ln["word_confs"]), 2),
                "bbox": ln["box"],
                "word_confs": ln["word_confs"],
                "words": ln["word_boxes"],
            }
        )
    return out


def lines_to_text(lines: list[dict]) -> str:
    parts, prev = [], None
    for ln in lines:
        para = (ln["block"], ln["par"])
        if prev is not None and para != prev:
            parts.append("")
        parts.append(ln["text"])
        prev = para
    return "\n".join(parts) + "\n"
