"""Keep a server's books in step with the material folder on Proton Drive (`amocr sync`).

The server works on its own copy (data/works/<id>/): the viewer reads and saves there on every
page view. Proton stays the team's store: a scheduled `amocr sync` brings down what volunteers and
OCR workers pushed, then pushes the server's proofreading back up.

  pull   new readings and pages from the material folder; never overwrites the server's files
         (a page saved on the server stays as saved; a differing copy on Proton is reported)
  push   the book's export folder (readings, saved text, history, status), only when something
         changed since the last push: a 460-page book isn't uploaded every half hour for nothing

What never goes to Proton: members, passwords, sessions and tokens (data/hosted/), and the
server's settings. They aren't part of a book's export.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Work, data_dir, load_works

STALE_LOCK = 2 * 3600  # seconds: a sync that died leaves its lock; after this, the next one goes ahead


def _state_path(work: Work) -> Path:
    return work.workdir / "sync.json"


def _state(work: Work) -> dict:
    p = _state_path(work)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def fingerprint(work: Work) -> str:
    """What a push would carry: every reading, saved page (with its history) and assembled build,
    by path, size and modification time. Changes when anything that goes to Proton changes."""
    h = hashlib.sha256()
    roots = [work.workdir / "pages", work.gt_dir, work.workdir / "units"]
    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if f.is_file() and (root != work.workdir / "pages" or (f.parent.name == "ocr" and f.suffix in (".json", ".txt"))):
                st = f.stat()
                h.update(f"{f.relative_to(work.workdir).as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


class Locked(Exception):
    pass


class _Lock:
    """One sync at a time on this machine (a scheduled one and a manual one, say)."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > STALE_LOCK:
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise Locked(f"another sync is running ({self.path}); try again later") from None
        os.write(fd, f"{os.getpid()} {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n".encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def sync_book(work: Work, push_unchanged: bool = False) -> dict:
    """Pull, then push if the book changed since its last push. Returns what happened."""
    from . import book

    out = {"book": work.id}
    if not work.remote:
        return out | {"skipped": "no Proton path (added from a local file)"}
    out["pulled"] = book.pull(work)
    fp = fingerprint(work)
    st = _state(work)
    if fp == st.get("pushed") and not push_unchanged:
        out["pushed"] = "unchanged"
    else:
        out["pushed"] = book.push(work)
        st.update(pushed=fingerprint(work), pushed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        _state_path(work).write_text(json.dumps(st, indent=1), encoding="utf-8")
    return out


def sync(ids: list[str] | None = None, push_unchanged: bool = False, log=print) -> int:
    """Sync the named books, or every book with a Proton path. One book failing doesn't stop the
    others. Returns the number of books that failed."""
    works = load_works()
    chosen = [works[i] for i in ids] if ids else [w for w in works.values() if w.remote]
    failed = 0
    with _Lock(data_dir() / "sync.lock"):
        for w in chosen:
            try:
                r = sync_book(w, push_unchanged)
            except (SystemExit, Exception) as e:  # noqa: BLE001 - report, carry on with the next book
                failed += 1
                r = {"book": w.id, "failed": str(e)[:300]}
            _record(r)
            log(_line(r))
    return failed


def _line(r: dict) -> str:
    if "failed" in r:
        return f"{r['book']}: FAILED: {r['failed']}"
    if "skipped" in r:
        return f"{r['book']}: skipped, {r['skipped']}"
    p = r["pulled"]
    pulled = "nothing on Proton yet" if p.get("remote") == "none yet" else (
        f"{p.get('results', 0)} readings, {p.get('groundtruth', 0)} saved pages pulled"
        + (f"; {p['kept_local']} files differ on Proton, the server's kept" if p.get("kept_local") else ""))
    pushed = "nothing new to push" if r["pushed"] == "unchanged" else f"pushed to {r['pushed']}"
    return f"{r['book']}: {pulled}; {pushed}"


def _record(r: dict) -> None:
    """Append to data/sync.log, one JSON line per book per run."""
    try:
        with (data_dir() / "sync.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds")} | r, ensure_ascii=False) + "\n")
    except OSError:
        pass
