"""An OCR worker on a member's machine: leases pages from a hosted server's queue, reads them with the
engines installed here (Tesseract, Surya), returns the readings, and deletes its copies of the images.
Every connection goes out from this machine (docs/plan.md, "OCR workers")."""

from __future__ import annotations

import socket
import tempfile
import time
from pathlib import Path


def available(wanted: list[str] | None = None) -> dict:
    """The engines this machine can run, as {name: engine}, with their exact versions."""
    from .engines import get_engine

    out = {}
    for name in wanted or ["tesseract", "surya"]:
        try:
            eng = get_engine(name)
            eng.version()
            out[name] = eng
        except (SystemExit, Exception) as e:        # not installed here: simply not offered
            print(f"  {name}: not available ({str(e).splitlines()[0][:100]})")
    return out


def run(server: str, token: str | None = None, engines: list[str] | None = None, batch: int = 10,
        once: bool = False, idle: float = 30, log=print) -> int:
    from librarian import remote

    from . import __version__

    engs = available(engines)
    if not engs:
        raise SystemExit("no OCR engine here: install Tesseract (amocr setup-models) or Surya (uv sync --extra surya)")
    host = socket.gethostname()
    log(f"worker on {host} for {server}: " + ", ".join(f"{n} {e.version()}" for n, e in engs.items()))
    done = 0
    try:
        while True:
            jobs = remote.call(server, "/api/ocr/lease", token, body={"engines": list(engs), "n": batch, "host": host}).get("jobs", [])
            if not jobs:
                if once:
                    break
                time.sleep(idle)
                continue
            for j in jobs:
                eng = engs[j["engine"]]
                with tempfile.TemporaryDirectory() as td:
                    img = Path(td) / "page.png"
                    try:
                        img.write_bytes(remote.fetch(server, j["image"], token))
                        res = eng.run(img)
                        rec = res.to_json() | {"amocr_version": __version__}
                        remote.call(server, "/api/ocr/result", token,
                                    body={"job": j["job"], "key": j["key"], "label": f"{eng.label}-{eng.version()}", "record": rec})
                        done += 1
                        log(f"  {j['book']} p{j['page']}: {j['engine']} conf {res.confidence}  {res.seconds}s  ({done} done)")
                    except (Exception, SystemExit) as e:
                        log(f"  {j['book']} p{j['page']}: failed ({str(e)[:120]}); back to the queue")
                        try:
                            remote.call(server, "/api/ocr/release", token, body={"job": j["job"], "key": j["key"], "error": str(e)})
                        except SystemExit:
                            pass
                # the page image was in the temporary folder, now gone
    except KeyboardInterrupt:
        log("stopped; any pages still leased go back to the queue when their lease expires")
    finally:
        for e in engs.values():
            e.close()
    log(f"{done} page(s) read")
    return done
