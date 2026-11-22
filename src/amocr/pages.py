"""Inventory PDF pages and render them to images for OCR."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from .textcheck import classify


def inventory(pdf: Path) -> list[dict]:
    """One record per page: geometry, embedded image, text-layer verdict."""
    doc = pymupdf.open(pdf)
    rows = []
    for i, page in enumerate(doc, start=1):
        imgs = page.get_images(full=True)
        img = imgs[0] if imgs else None
        text = page.get_text()
        rows.append(
            {
                "page": i,
                "width_pt": round(page.rect.width, 1),
                "height_pt": round(page.rect.height, 1),
                "rotation": page.rotation,
                "images": len(imgs),
                "image_px": [img[2], img[3]] if img else None,
                "image_codec": img[8] if img and len(img) > 8 else None,
                "text_chars": len(text.strip()),
                "text_layer": classify(text),
            }
        )
    return rows


def native_dpi(row: dict) -> int:
    """DPI of the embedded scan, accounting for page rotation."""
    if not row["image_px"]:
        return 300
    w_px, h_px = row["image_px"]
    if row["rotation"] in (90, 270):
        w_px, h_px = h_px, w_px
    return round(w_px / (row["width_pt"] / 72))


def render(pdf: Path, page: int, out: Path, dpi: int) -> Path:
    """Render one page (1-based), upright, grayscale PNG."""
    doc = pymupdf.open(pdf)
    pix = doc[page - 1].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(out)
    return out


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
