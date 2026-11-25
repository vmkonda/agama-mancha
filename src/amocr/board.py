"""Who is working on which book, and how far each book has got (docs/plan.md, phase B).

Proton Drive has no locks, so nobody edits a shared file. Each person writes only their
own small file, and everyone reads all of them:

  shared: <material folder>/catalog/board/<operator>.json
  local:  data/library/board/<operator>.json   (copies of everyone's, from the last sync)

A person's file:
  {"operator", "updated",
   "books":    {<sha1>: {"path", "title", "claimed", "since", "last_active", "stage", "progress"}},
   "releases": [{"key", "holder", "since", "at", "why"}]}   stale claims of others they released

Books are keyed by the PDF's SHA-1 (the catalog's checksum), so a claim survives the
library being reorganised.

Claims: the earliest claim that is still held and not released wins. *Work on this*
writes the claim, uploads it, reads the board again and withdraws if someone else
claimed the book first. A claim with no activity for STALE_DAYS days is stale; anyone
may then release it, and the release is recorded in the releaser's own file.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalog import Work, data_dir

STALE_DAYS = 14
STAGES = ["listed", "inventoried", "read", "reviewed", "proofreading", "verified", "assembled"]
STAGE_LABEL = {"listed": "listed", "inventoried": "inventoried", "read": "read by OCR", "reviewed": "reviewed by Claude",
               "proofreading": "proofreading", "verified": "verified", "assembled": "assembled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_days(at: str | None, now: datetime | None = None) -> float | None:
    if not at:
        return None
    return ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(at)).total_seconds() / 86400


def file_name(operator: str) -> str:
    """The operator's board file name: letters, digits, '.', '-', '_' only."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", operator.strip()).strip("._") or "anonymous"
    return f"{safe}.json"


def local_dir() -> Path:
    return data_dir() / "library" / "board"


def load_all() -> dict[str, dict]:
    """Everyone's board files from the last sync (plus this person's own, always current)."""
    out = {}
    for f in sorted(local_dir().glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict) and d.get("operator"):
            out[d["operator"]] = d
    return out


def load_mine(operator: str) -> dict:
    p = local_dir() / file_name(operator)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("operator") == operator:
            return d
    return {"operator": operator, "updated": None, "books": {}, "releases": []}


def save_mine(mine: dict) -> Path:
    local_dir().mkdir(parents=True, exist_ok=True)
    mine["updated"] = _now()
    p = local_dir() / file_name(mine["operator"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(mine, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


# ---- the board: everyone's files merged (pure) -----------------------------------------

def merge(files: dict[str, dict], now: datetime | None = None) -> dict[str, dict]:
    """Per book key: {holder, since, last_active, stale, stage, progress, by, claims}."""
    now = now or datetime.now(timezone.utc)
    released = {(r.get("key"), r.get("holder"), r.get("since")) for d in files.values() for r in d.get("releases", [])}
    board: dict[str, dict] = {}
    for op, d in files.items():
        for key, b in (d.get("books") or {}).items():
            e = board.setdefault(key, {"holder": None, "claims": [], "stage": "listed", "progress": None, "by": None,
                                       "path": b.get("path"), "title": b.get("title")})
            if b.get("claimed") and (key, op, b.get("since")) not in released:
                e["claims"].append({"operator": op, "since": b.get("since") or "", "last_active": b.get("last_active")})
            # The furthest stage anyone has reported, with who reported it.
            st = b.get("stage") or "listed"
            if STAGES.index(st) > STAGES.index(e["stage"]) or (st == e["stage"] and e["progress"] is None):
                e.update(stage=st, progress=b.get("progress"), by=op)
    for e in board.values():
        e["claims"].sort(key=lambda c: (c["since"], c["operator"]))
        if e["claims"]:
            c = e["claims"][0]
            age = _age_days(c["last_active"] or c["since"], now)
            e.update(holder=c["operator"], since=c["since"], last_active=c["last_active"],
                     stale=age is not None and age > STALE_DAYS)
    return board


# ---- progress of a book on this machine ------------------------------------------------

def progress(work: Work) -> dict:
    """Page counts per step, from the book's files on this machine."""
    inv = work.workdir / "inventory.jsonl"
    pages = sum(1 for ln in inv.read_text(encoding="utf-8").splitlines() if ln.strip()) if inv.exists() else 0
    from . import ladder

    read = surya = claude = proofread = checked = validated = blank = problem = 0
    last = None
    for p in range(1, pages + 1):
        d = work.page_dir(p) / "ocr"
        labels = [f.stem for f in d.glob("*.json")] if d.exists() else []
        read += bool(labels)
        surya += any(lb.startswith("surya") for lb in labels)
        claude += any(lb.startswith("claude") for lb in labels)
        gt = work.gt_dir / f"p{p:04d}.txt"
        if gt.exists():
            proofread += 1
            meta = gt.with_suffix(".meta.json")
            m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            st = ladder.of(m)
            checked += st in ladder.CHECKED
            validated += st == "validated"
            blank += st == "blank"
            problem += st == "problem"
            last = max(last or "", m.get("saved") or "")
    builds = sorted((work.workdir / "units").glob("v[0-9][0-9][0-9]")) if (work.workdir / "units").exists() else []
    assembled = False
    if builds and (builds[-1] / "build.json").exists():
        b = json.loads((builds[-1] / "build.json").read_text(encoding="utf-8"))
        done = b.get("validated_units", 0)
        assembled = bool(done) and done == sum(b.get("units", {}).values())
    # proofread: pages with saved text; checked: every line checked by one person (proofread or
    # validated); verified: nothing left to do (validated, or no text on the page).
    return {"pages": pages, "read": read, "surya": surya, "claude": claude, "proofread": proofread,
            "checked": checked, "validated": validated, "blank": blank, "problem": problem,
            "verified": validated + blank, "last_saved": last or None, "builds": len(builds), "assembled": assembled}


def stage_of(p: dict | None) -> str:
    if not p or not p.get("pages"):
        return "listed"
    n = p["pages"]
    if p.get("assembled"):          # the latest build has only validated units
        return "assembled"
    if p.get("verified", 0) >= n:    # every page validated (or without text)
        return "verified"
    if p.get("proofread"):
        return "proofreading"
    if p.get("claude", 0) >= n:
        return "reviewed"
    if p.get("read", 0) >= n:
        return "read"
    return "inventoried"


def sha1_of(work: Work) -> str | None:
    """The PDF's SHA-1, cached in book.json (the catalog keys books by it)."""
    if work.extra.get("sha1"):
        return work.extra["sha1"]
    if not work.source.exists():
        return None
    h = hashlib.sha1()
    with work.source.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    work.extra["sha1"] = h.hexdigest()
    if work.origin == "book":
        work.save()
    return work.extra["sha1"]


def catalog_path(work: Work, root: str) -> str | None:
    root = root.rstrip("/")
    return work.remote[len(root) + 1:] if work.remote and root and work.remote.startswith(root + "/") else None


def update_mine(mine: dict, works: dict[str, Work], root: str) -> dict:
    """Refresh progress for every book on this machine that came from the library."""
    for w in works.values():
        path = catalog_path(w, root)
        key = sha1_of(w) if path else None
        if not key:
            continue
        p = progress(w)
        b = mine["books"].setdefault(key, {"path": path, "title": w.title, "claimed": False, "since": None})
        if b.get("progress") != p:
            b["last_active"] = _now()
        b.update(path=path, title=w.title, progress=p, stage=stage_of(p), book=w.id)
    return mine


# ---- syncing with the drive (through the wrapper; writes only the operator's own file) --

def remote_dir(cfg, sub: str = "board") -> str | None:
    from . import library

    d = library.remote_dir(cfg)
    return posixpath.join(d, sub) if d else None


def sync(pd, cfg, sub: str = "board") -> dict[str, dict]:
    """Download everyone's files from catalog/<sub>/ (the board, or the inventory) into
    data/library/<sub>/. Returns the board files (for sub="board")."""
    import shutil
    import tempfile

    rdir = remote_dir(cfg, sub)
    ldir = data_dir() / "library" / sub
    ldir.mkdir(parents=True, exist_ok=True)
    if rdir and pd.exists(rdir):
        names = [n for n in pd.list(rdir) if n.endswith(".json")]
        mine = file_name(cfg.operator) if cfg.operator else None
        tmp = Path(tempfile.mkdtemp(dir=data_dir()))
        try:
            for n in names:
                if n == mine:
                    continue  # this machine's copy is the newest
                pd.download(posixpath.join(rdir, n), tmp)
                got = tmp / n
                if got.exists():
                    try:
                        d = json.loads(got.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    # A file speaks only for the operator it is named after.
                    if isinstance(d, dict) and file_name(str(d.get("operator", ""))) == n:
                        shutil.copy2(got, ldir / n)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # Our own file: take the drive's copy only if this machine has none (a new machine).
        if mine and mine in names and not (ldir / mine).exists():
            pd.download(posixpath.join(rdir, mine), ldir)
    return load_all() if sub == "board" else {}


def publish(pd, cfg, mine: dict) -> str:
    return publish_file(pd, cfg, save_mine(mine), "board")


def publish_file(pd, cfg, p: Path, sub: str) -> str:
    """Upload this person's own file to catalog/<sub>/ in the material folder."""
    from .proton import results_root

    rdir = remote_dir(cfg, sub)
    if not rdir:
        return "saved here only: no material folder set"
    if not pd.exists(results_root(cfg.proton_root, cfg.material)):
        return "saved here only: the material folder doesn't exist on the drive"
    pd.mkdir_p(rdir)
    pd.upload(p, rdir)
    return f"shared to {rdir}"


# ---- the actions -------------------------------------------------------------------------

def _context():
    from . import book
    from .catalog import load_works

    pd, cfg = book._proton()
    if not cfg.operator:
        raise SystemExit('set your name first: `amocr init --operator "<your Proton username>"`')
    return pd, cfg, load_works()


def find(cat: dict, what: str, works: dict[str, Work]) -> dict:
    """A catalog entry by SHA-1, book id (B-…), or path (or a unique part of one)."""
    from . import library

    entries = [e for e in cat.get("entries", []) if e.get("state") != "gone"]
    if what in works:
        w = works[what]
        root = cat.get("root", "")
        hit = [e for e in entries if e.get("sha1") and e["sha1"] == sha1_of(w)] or \
              [e for e in entries if catalog_path(w, root) == e["path"]]
        if hit:
            return hit[0]
    hit = [e for e in entries if e.get("sha1") == what or e["path"] == what]
    if not hit:
        q = what.lower()
        hit = [e for e in entries if q in "/".join(library.split_path(e["path"])).lower()]
    if len(hit) != 1:
        raise SystemExit(f"{len(hit)} books in the catalog match {what!r}" + (
            ":\n  " + "\n  ".join(e["path"] for e in hit[:10]) if hit else "; run `amocr catalog refresh`?"))
    return hit[0]


def refresh_board() -> dict:
    """Sync, update this person's progress, and share it. The board, merged."""
    from . import library

    pd, cfg, works = _context()
    sync(pd, cfg)
    mine = update_mine(load_mine(cfg.operator), works, library.load().get("root", cfg.proton_root))
    publish(pd, cfg, mine)
    return merge(load_all())


def claim(what: str) -> dict:
    """Claim a book: write the claim, share it, read the board back to confirm."""
    from . import library

    pd, cfg, works = _context()
    cat = library.load()
    e = find(cat, what, works)
    key = e.get("sha1")
    if not key:
        raise SystemExit(f"{e['path']} has no checksum in the catalog; refresh the catalog first")
    board = merge(sync(pd, cfg))
    cur = board.get(key, {})
    if cur.get("holder") and cur["holder"] != cfg.operator and not cur.get("stale"):
        return {"ok": False, "why": f"{cur['holder']} has been working on it since {cur['since'][:10]}", "entry": e}
    if cur.get("holder") and cur["holder"] != cfg.operator:
        return {"ok": False, "why": f"{cur['holder']}'s claim is stale (no activity for {STALE_DAYS} days): "
                                    "release it first", "stale": True, "entry": e}
    mine = load_mine(cfg.operator)
    b = mine["books"].setdefault(key, {"path": e["path"], "title": e["name"].removesuffix(".pdf")})
    if not b.get("claimed"):
        b.update(claimed=True, since=_now(), last_active=_now())
    shared = publish(pd, cfg, mine)
    # Read back: if someone else claimed it first in the meantime, withdraw.
    after = merge(sync(pd, cfg)).get(key, {})
    if after.get("holder") not in (None, cfg.operator):
        b.update(claimed=False)
        publish(pd, cfg, mine)
        return {"ok": False, "why": f"{after['holder']} claimed it a moment earlier", "entry": e}
    return {"ok": True, "shared": shared, "entry": e, "since": b["since"]}


def release(what: str, why: str = "") -> dict:
    """Release your own claim, or a stale claim of someone else (recorded in your file)."""
    from . import library

    pd, cfg, works = _context()
    e = find(library.load(), what, works)
    key = e.get("sha1")
    cur = merge(sync(pd, cfg)).get(key or "", {})
    mine = load_mine(cfg.operator)
    if cur.get("holder") == cfg.operator or (mine["books"].get(key, {}).get("claimed")):
        mine["books"][key]["claimed"] = False
        mine["books"][key]["released"] = _now()
        return {"ok": True, "shared": publish(pd, cfg, mine), "entry": e}
    if not cur.get("holder"):
        return {"ok": False, "why": "nobody is working on it", "entry": e}
    if not cur.get("stale"):
        return {"ok": False, "why": f"{cur['holder']}'s claim isn't stale; only they can release it now", "entry": e}
    mine["releases"].append({"key": key, "holder": cur["holder"], "since": cur["since"], "at": _now(),
                             "why": why or f"no activity for {STALE_DAYS} days"})
    return {"ok": True, "released": cur["holder"], "shared": publish(pd, cfg, mine), "entry": e}


def stale_after(since: str) -> str:
    return (datetime.fromisoformat(since) + timedelta(days=STALE_DAYS)).date().isoformat()
