"""Volunteer operations: add/fetch a book, export results, push to and pull from Proton Drive.

Shared-drive layout in the material folder, next to the originals' tree:

  <material folder>/<path of the original>/<book>.amocr/
    book.json                 id, source fingerprint, per-page status and credits
    book.txt                  best text of every page, in order
    pages/p0231/<result>.json one file per engine result (text, regions, confidence, operator)
    pages/p0231/<result>.txt
    groundtruth/p0231.txt     human-verified page text, if any
"""

from __future__ import annotations

import json
import posixpath
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import config as cfgmod
from .catalog import Work, book_id, data_dir, load_works, sha256_of
from .pages import inventory, read_jsonl, write_jsonl
from .proton import Proton, ProtonError, mirror_dir, results_root

# Which result stands for a page in book.txt, best first.
PREFERENCE = ["groundtruth", "claude-code-correct", "claude-code-direct", "tesseract-san+hin"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add(pdf: Path, title: str | None = None, remote: str | None = None, restricted: bool = False,
        languages: list[str] | None = None, move: bool = False) -> Work:
    """Register a PDF. The id comes from its checksum, so every volunteer gets the same id."""
    sha = sha256_of(pdf)
    wid = book_id(sha)
    existing = load_works().get(wid)
    work = existing or Work(id=wid, title=title or pdf.stem, languages=languages or ["san", "hin"], sha256=sha,
                            source_name=pdf.name, remote=remote, restricted=restricted)
    if existing and remote and not existing.remote:
        work.remote = remote
    if restricted:
        work.restricted = True
    work.source.parent.mkdir(parents=True, exist_ok=True)
    if not work.source.exists():
        (shutil.move if move else shutil.copy2)(pdf, work.source)
    if work.origin == "book":
        work.save()
    inv = work.workdir / "inventory.jsonl"
    if not inv.exists():
        write_jsonl(inventory(work.source), inv)
    return work


def best_label(page_dir: Path, has_gt: bool) -> str | None:
    if has_gt:
        return "groundtruth"
    labels = sorted(f.stem for f in (page_dir / "ocr").glob("*.json"))
    for pref in PREFERENCE[1:]:
        for label in labels:
            if label.startswith(pref):
                return label
    return labels[0] if labels else None


def page_status(work: Work) -> dict[int, dict]:
    n = len(read_jsonl(work.workdir / "inventory.jsonl"))
    out = {}
    for p in range(1, n + 1):
        d = work.page_dir(p)
        results = []
        for f in sorted((d / "ocr").glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            results.append({"label": f.stem, "operator": rec.get("operator", ""), "created": rec.get("created", "")})
        gt = (work.gt_dir / f"p{p:04d}.txt").exists()
        meta = work.gt_dir / f"p{p:04d}.meta.json"
        review = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None
        out[p] = {"results": results, "groundtruth": gt, "review": review, "best": best_label(d, gt)}
    return out


def export(work: Work) -> Path:
    """Build the shareable folder for this book under data/works/<id>/export/<stem>.amocr."""
    out = work.workdir / "export" / f"{work.stem}.amocr"
    if out.exists():
        shutil.rmtree(out)
    (out / "pages").mkdir(parents=True)
    status = page_status(work)
    parts = []
    for p, st in status.items():
        src = work.page_dir(p) / "ocr"
        if st["results"]:
            dst = out / "pages" / f"p{p:04d}"
            dst.mkdir()
            for f in src.glob("*.*"):
                if f.suffix in (".json", ".txt"):
                    shutil.copy2(f, dst / f.name)
        gt = work.gt_dir / f"p{p:04d}.txt"
        if gt.exists():
            (out / "groundtruth").mkdir(exist_ok=True)
            for f in work.gt_dir.glob(f"p{p:04d}.*"):
                shutil.copy2(f, out / "groundtruth" / f.name)
        best = st["best"]
        if best == "groundtruth":
            text = gt.read_text(encoding="utf-8")
        elif best:
            text = (src / f"{best}.txt").read_text(encoding="utf-8")
        else:
            text = "[not yet OCR'd]\n"
        parts.append(f"=== page {p} ({best or 'none'}) ===\n{text.rstrip()}\n")
    (out / "book.txt").write_text("\n".join(parts), encoding="utf-8")
    units = work.workdir / "units"
    if units.exists():      # assembled builds (amocr assemble); each is written once and never changed
        shutil.copytree(units, out / "units")
    meta = {
        "id": work.id, "title": work.title, "sha256": work.sha256, "source_name": work.source_name,
        "remote": work.remote, "languages": work.languages, "restricted": work.restricted,
        "amocr_version": __version__, "updated": now(), "updated_by": cfgmod.load().operator,
        "pages_total": len(status),
        "pages_done": {
            "any": sum(1 for s in status.values() if s["results"]),
            "claude": sum(1 for s in status.values() if any(r["label"].startswith("claude") for r in s["results"])),
            "groundtruth": sum(1 for s in status.values() if s["groundtruth"]),
        },
        "pages": {str(p): s for p, s in status.items() if s["results"] or s["groundtruth"]},
    }
    (out / "book.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def merge_in(work: Work, folder: Path) -> dict[str, int]:
    """Copy results from a downloaded .amocr folder into local storage. Never overwrites local files."""
    counts = {"results": 0, "groundtruth": 0, "kept_local": 0}
    for f in sorted((folder / "pages").glob("p*/*.*")):
        page = int(f.parent.name[1:])
        dst = work.page_dir(page) / "ocr" / f.name
        if dst.exists():
            counts["kept_local"] += f.suffix == ".json" and dst.read_bytes() != f.read_bytes()
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        counts["results"] += f.suffix == ".json"
    for f in sorted((folder / "groundtruth").glob("p*.*")):
        dst = work.gt_dir / f.name
        if dst.exists():
            counts["kept_local"] += dst.read_bytes() != f.read_bytes()
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        counts["groundtruth"] += f.suffix == ".txt"
    return counts


def _proton() -> tuple[Proton, cfgmod.Config]:
    cfg = cfgmod.load()
    if not cfg.proton_root:
        raise SystemExit("team folder not set; run `amocr init --proton-root \"/shared-with-me/<team folder>\"`")
    _need_material(cfg)
    try:
        return Proton(cfg.proton_bin, write_root=results_root(cfg.proton_root, cfg.material)), cfg
    except ProtonError as e:
        raise SystemExit(str(e)) from None


def remote_results(work: Work) -> str:
    if not work.remote:
        raise SystemExit(f"{work.id} has no Proton path; it was added from a local file. Use `amocr fetch` instead.")
    return _mirror(work.remote, cfgmod.load())


def _need_material(cfg: cfgmod.Config) -> None:
    # Without it the write root would be the library itself; never guess.
    if not cfg.material.strip():
        raise SystemExit('material folder not set; run `amocr init --material "/shared-with-me/<material folder>"` '
                         "(ask the coordinator which folder; see docs/drive-setup.md)")


def _mirror(remote_pdf: str, cfg: cfgmod.Config) -> str:
    _need_material(cfg)
    try:
        return mirror_dir(remote_pdf, cfg.proton_root, cfg.material)
    except ValueError as e:
        raise SystemExit(str(e)) from None


def fetch(remote_pdf: str, title: str | None = None, restricted: bool = False) -> tuple[Work, dict]:
    pd, cfg = _proton()
    _mirror(remote_pdf, cfg)  # fail early if outside the team folder
    tmp = Path(tempfile.mkdtemp(dir=data_dir()))
    try:
        pd.download(remote_pdf, tmp)
        got = tmp / posixpath.basename(remote_pdf)
        if not got.exists():
            raise SystemExit(f"download of {remote_pdf} produced no file")
        work = add(got, title=title, remote=remote_pdf, restricted=restricted, move=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return work, pull(work)


def pull(work: Work) -> dict:
    """Bring down results other volunteers already pushed for this book."""
    pd, _ = _proton()
    remote = remote_results(work)
    if not pd.exists(remote):
        return {"remote": "none yet"}
    tmp = Path(tempfile.mkdtemp(dir=data_dir()))
    try:
        pd.download(remote, tmp)
        return merge_in(work, tmp / posixpath.basename(remote))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def push(work: Work) -> str:
    pd, _ = _proton()
    if not cfgmod.load().operator:
        raise SystemExit("set your name first so pages are credited: `amocr init --operator \"Your Name\"`")
    remote = remote_results(work)
    local = export(work)
    parent = posixpath.dirname(remote)
    try:
        pd.mkdir_p(parent)
        pd.upload(local, parent)
    except ProtonError as e:
        raise SystemExit(str(e)) from None
    return remote
