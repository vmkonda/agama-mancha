"""Per-machine settings in data/config.toml (never committed)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass

from .catalog import data_dir


@dataclass
class Config:
    operator: str = ""  # name credited on every page this machine processes
    proton_bin: str = "proton-drive"  # path to the Proton Drive CLI
    proton_root: str = ""  # team folder, e.g. "/shared-with-me/Library"
    # Results folder. A full path ("/shared-with-me/OCR Mirror") when it is its own share
    # (recommended: editor access there, viewer access to the originals); otherwise a
    # folder name inside proton_root.
    mirror: str = "OCR Mirror"


def path():
    return data_dir() / "config.toml"


def load() -> Config:
    p = path()
    if not p.exists():
        return Config()
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    return Config(**{k: v for k, v in raw.items() if k in Config.__dataclass_fields__})


def save(cfg: Config) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)

    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    p.write_text("".join(f"{k} = {q(v)}\n" for k, v in asdict(cfg).items()), encoding="utf-8")
