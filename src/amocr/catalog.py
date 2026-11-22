"""Books (works) and their on-disk layout under data/.

Two sources of books:
- works.toml in the repo: pilot books registered by hand.
- data/works/<id>/book.json: books a volunteer added or fetched.
Ground truth lives next to each book (data/works/<id>/groundtruth/), never in git:
it is book text.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("AMOCR_DATA", REPO_ROOT / "data"))


@dataclass
class Work:
    id: str
    title: str
    languages: list[str]
    sha256: str
    script: str = "Devanagari"
    source_name: str = ""  # original file name, e.g. "Book Title.pdf"
    remote: str | None = None  # Proton Drive path of the original PDF
    restricted: bool = False  # restricted texts never go to Claude
    origin: str = "book"  # "repo" (works.toml) or "book" (book.json)
    extra: dict = field(default_factory=dict)

    @property
    def source(self) -> Path:
        return data_dir() / "sources" / f"{self.id}.pdf"

    @property
    def workdir(self) -> Path:
        return data_dir() / "works" / self.id

    @property
    def gt_dir(self) -> Path:
        return self.workdir / "groundtruth"

    @property
    def stem(self) -> str:
        return Path(self.source_name).stem if self.source_name else self.id

    def page_dir(self, page: int) -> Path:
        """page is 1-based PDF page index (not the printed page number)."""
        return self.workdir / "pages" / f"{page:04d}"

    def save(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d.pop("origin")
        (self.workdir / "book.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def book_id(sha256: str) -> str:
    """Same PDF -> same id on every volunteer's machine."""
    return "B-" + sha256[:10]


def load_works(path: Path | None = None) -> dict[str, Work]:
    path = path or REPO_ROOT / "works.toml"
    works: dict[str, Work] = {}
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        for w in raw.get("work", []):
            known = {k: w[k] for k in ("id", "title", "languages", "sha256") if k in w}
            extra = {k: v for k, v in w.items() if k not in known and k != "script"}
            works[w["id"]] = Work(script=w.get("script", "Devanagari"), origin="repo", extra=extra, **known)
    for bj in sorted((data_dir() / "works").glob("*/book.json")):
        d = json.loads(bj.read_text(encoding="utf-8"))
        d.pop("origin", None)
        works.setdefault(d["id"], Work(**d, origin="book"))
    return works


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_source(work: Work) -> None:
    """Refuse to work on a file whose checksum doesn't match the catalog."""
    if not work.source.exists():
        hint = f" Run `amocr fetch \"{work.remote}\"`." if work.remote else ""
        raise SystemExit(f"{work.id}: source PDF not found at {work.source}.{hint}")
    if work.sha256 == "PENDING":
        raise SystemExit(f"{work.id}: sha256 is PENDING in works.toml. Run `amocr checksum {work.id}` and paste it in.")
    actual = sha256_of(work.source)
    if actual != work.sha256:
        raise SystemExit(f"{work.id}: checksum mismatch (catalog {work.sha256[:12]}…, file {actual[:12]}…)")
