"""Importing an e-text into the library from the app: from GRETIL's catalogue or an uploaded TEI file.

One import at a time, in a background thread, with a log the page polls: fetch or save the file,
read its structure into units, add the work to the library, embed its units and add them to the
index. Licence and source come from the file's header unless the person gives them.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from amocr.catalog import data_dir

JOB: dict = {"state": "idle", "log": [], "result": None, "error": None}
_LOCK = threading.Lock()
MAX_UPLOAD = 20_000_000


def _run(fn, label: str) -> dict:
    with _LOCK:
        if JOB["state"] == "running":
            raise RuntimeError("an import is already running; wait for it to finish")
        JOB.update(state="running", log=[f"{label}"], result=None, error=None, started=time.time())

    def work():
        try:
            JOB["result"] = fn(lambda msg: JOB["log"].append(str(msg)))
            JOB["state"] = "done"
        except Exception as e:  # shown to the person, not swallowed
            JOB.update(state="failed", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return dict(JOB)


def _finish(xml: Path, log, **meta) -> dict:
    from . import etext, index, store

    log("reading its structure…")
    m = etext.ingest(xml, **meta)
    log(f"{m['id']} {m['title']}: {m['units']} passages ({', '.join(m['layers'])})")
    store.reload()
    log("embedding and indexing (a few seconds per hundred passages)…")
    index.add_work(m["id"], log=log)
    store.reload()
    log("done: it's in the library and searchable")
    return m


def from_gretil(path: str, title: str | None = None) -> dict:
    from . import gretil

    def go(log):
        log(f"downloading {path} from GRETIL…")
        xml = gretil.download(path)
        return _finish(xml, log, title=title, origin="GRETIL")
    return _run(go, f"Importing {title or path}")


def from_upload(name: str, text: str, title: str = "", author: str = "", licence: str = "", source: str = "") -> dict:
    if len(text.encode("utf-8")) > MAX_UPLOAD:
        raise ValueError("file too large (20 MB at most)")
    if "<TEI" not in text[:5000] and "<tei" not in text[:5000].lower():
        raise ValueError("this isn't a TEI XML e-text (GRETIL's TEI files work; plain text doesn't yet)")
    safe = re.sub(r"[^\w.-]+", "_", Path(name or "upload.xml").stem)[:80] or "upload"
    out = data_dir() / "etexts" / "uploads" / f"{safe}.xml"

    def go(log):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        log(f"saved {out.name}")
        return _finish(out, log, title=title or None, author=author or None, licence=licence or None,
                       source=source or None, origin="upload")
    return _run(go, f"Importing {name}")


def status() -> dict:
    return {k: JOB.get(k) for k in ("state", "log", "result", "error")}
