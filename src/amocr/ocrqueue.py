"""The OCR job queue on a hosted server: pages waiting for an engine, leased to workers on members'
machines (docs/plan.md, "OCR workers").

A coordinator queues a book for an engine (every page with no usable text layer and no reading from
that engine yet). A worker leases a batch for the engines it has; while the lease lasts nobody else gets
those pages; an expired lease goes back to the queue, and a page that fails three times is set aside.
A returned reading is saved exactly like a local `amocr ocr` result (pages/NNNN/ocr/<label>.json and
.txt), never over an existing one. Workers serve everyone's jobs: they run local engines, which may be
shared (Claude is never a worker engine here).

State: data/hosted/ocr-queue.json, changed only under a lock.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Work, data_dir

ENGINES = ("tesseract", "surya")       # what a worker may be asked to run
LEASE_MINUTES = 15
MAX_ATTEMPTS = 3
_LOCK = threading.Lock()
_SEEN: dict[str, dict] = {}             # worker name -> {"at", "engines", "host"}


def path() -> Path:
    return data_dir() / "hosted" / "ocr-queue.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    p = path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"jobs": {}}


def _save(d: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(path())


def _has_reading(work: Work, page: int, engine: str) -> bool:
    ocr = work.page_dir(page) / "ocr"
    return ocr.exists() and any(ocr.glob(f"{engine}*.json"))


def add(work: Work, engine: str, pages: list[int] | None = None) -> int:
    """Queue the pages of a book that still need this engine. Returns how many were added."""
    from .pages import read_jsonl

    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {', '.join(ENGINES)}")
    rows = read_jsonl(work.workdir / "inventory.jsonl")
    if not rows:
        raise ValueError(f"{work.id} has no page inventory on this server")
    with _LOCK:
        d = _load()
        have = {(j["book"], j["page"], j["engine"]) for j in d["jobs"].values() if j["state"] != "failed"}
        n = 0
        for p in pages or range(1, len(rows) + 1):
            if p < 1 or p > len(rows):
                continue
            if rows[p - 1].get("text_layer") not in ("none", "suspect"):
                continue                                   # a usable text layer needs no OCR
            if (work.id, p, engine) in have or _has_reading(work, p, engine):
                continue
            jid = f"{work.id}-{p:04d}-{engine}"
            d["jobs"][jid] = {"book": work.id, "page": p, "engine": engine, "state": "queued", "attempts": 0,
                              "queued_at": _now()}
            n += 1
        _save(d)
    return n


def _expire(d: dict) -> None:
    now = time.time()
    for j in d["jobs"].values():
        if j["state"] == "leased" and j["lease"]["until"] < now:
            j["state"] = "queued"
            j.pop("lease", None)


def lease(who: str, engines: list[str], n: int = 10, host: str = "") -> list[dict]:
    """Lease up to n queued pages for engines this worker has (book by book, in page order)."""
    engines = [e for e in engines if e in ENGINES]
    _SEEN[who] = {"at": time.time(), "engines": engines, "host": host[:80]}
    with _LOCK:
        d = _load()
        _expire(d)
        todo = sorted((j for j in d["jobs"].items() if j[1]["state"] == "queued" and j[1]["engine"] in engines),
                      key=lambda kv: (kv[1]["book"], kv[1]["page"]))[:max(1, min(n, 50))]
        out = []
        for jid, j in todo:
            j["state"] = "leased"
            j["lease"] = {"by": who, "host": host[:80], "until": time.time() + LEASE_MINUTES * 60, "key": secrets.token_hex(8)}
            out.append({"job": jid, "key": j["lease"]["key"], "book": j["book"], "page": j["page"], "engine": j["engine"],
                        "image": f"/img/{j['book']}/{j['page']}"})
        _save(d)
    return out


def complete(works: dict, who: str, jid: str, key: str, label: str, record: dict) -> dict:
    """Save a worker's reading for a leased page (never over an existing reading) and close the job."""
    if not re.fullmatch(r"[\w.+-]{3,120}", label or ""):
        raise ValueError("bad engine label")
    if not isinstance(record, dict) or not isinstance(record.get("text"), str):
        raise ValueError("a reading needs its text")
    with _LOCK:
        d = _load()
        j = d["jobs"].get(jid)
        if not j or j["state"] != "leased" or j["lease"]["by"] != who or j["lease"]["key"] != key:
            raise ValueError("that page isn't leased to you (the lease may have expired)")
        if not label.startswith(j["engine"]):
            raise ValueError(f"this job wants {j['engine']}, not {label}")
        work = works.get(j["book"])
        if not work:
            raise ValueError(f"unknown book {j['book']}")
        out = work.page_dir(j["page"]) / "ocr" / f"{label}.json"
        if not out.exists():
            rec = {k: v for k, v in record.items() if k in ("text", "confidence", "engine", "engine_version", "config",
                                                            "lines", "seconds", "amocr_version")}
            rec |= {"work": j["book"], "page": j["page"], "operator": who, "worker": j["lease"].get("host", ""),
                    "created": _now(), "via": "ocr-worker"}
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            out.with_suffix(".txt").write_text(rec["text"], encoding="utf-8")
        j.update(state="done", done_by=who, done_at=_now(), label=label)
        j.pop("lease", None)
        _save(d)
    return {"saved": out.name}


def release(who: str, jid: str, key: str, error: str = "") -> dict:
    """A worker couldn't read a page: back to the queue, or set aside after three tries."""
    with _LOCK:
        d = _load()
        j = d["jobs"].get(jid)
        if not j or j["state"] != "leased" or j["lease"]["by"] != who or j["lease"]["key"] != key:
            raise ValueError("that page isn't leased to you")
        j["attempts"] = j.get("attempts", 0) + 1
        j["last_error"] = str(error)[:300]
        j["state"] = "failed" if j["attempts"] >= MAX_ATTEMPTS else "queued"
        j.pop("lease", None)
        _save(d)
    return {"state": j["state"]}


def status() -> dict:
    with _LOCK:
        d = _load()
        _expire(d)
    books: dict[str, dict] = {}
    for j in d["jobs"].values():
        b = books.setdefault(f"{j['book']} · {j['engine']}", {"queued": 0, "leased": 0, "done": 0, "failed": 0})
        b[j["state"]] += 1
    now = time.time()
    workers = {w: {"engines": s["engines"], "host": s["host"], "seconds_ago": int(now - s["at"])}
               for w, s in _SEEN.items() if now - s["at"] < 180}
    return {"books": books, "workers": workers}
