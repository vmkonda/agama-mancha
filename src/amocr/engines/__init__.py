"""OCR engines. Each engine turns one page image into an OcrResult."""

from __future__ import annotations

from .base import Engine, OcrResult
from .tesseract import Tesseract

ENGINES: dict[str, type[Engine]] = {"tesseract": Tesseract}


def get_engine(name: str, **kwargs) -> Engine:
    try:
        return ENGINES[name](**kwargs)
    except KeyError:
        raise SystemExit(f"unknown engine {name!r}; known: {', '.join(ENGINES)}") from None


__all__ = ["Engine", "OcrResult", "ENGINES", "get_engine"]
