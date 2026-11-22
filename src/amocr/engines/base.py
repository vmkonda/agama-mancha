from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class OcrResult:
    text: str
    confidence: float | None  # 0-100 page mean, None if the engine gives none
    engine: str
    engine_version: str
    config: dict
    lines: list[dict] = field(default_factory=list)  # [{text, conf, bbox}]
    seconds: float = 0.0
    cost_usd: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)


class Engine(ABC):
    name: str
    paid: bool = False
    price_per_page_usd: float = 0.0

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def config(self) -> dict: ...

    @abstractmethod
    def run(self, image: Path) -> OcrResult: ...

    @property
    def label(self) -> str:
        """Filename-safe id for this engine + config, e.g. tesseract-san+hin-psm3."""
        return self.name
