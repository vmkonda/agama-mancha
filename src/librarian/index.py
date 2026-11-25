"""The index: a derived, disposable search store over the library (design doc, "Index design").

It holds unit ids and searchable text only, never the canonical text: a search returns ids, and the
passage is then read from the library. Hybrid retrieval: keyword search (BM25 on IAST folded to plain
letters, so 'spanda', 'spanda' with diacritics and Devanagari all match) plus vector search (bge-m3
embeddings from the local Ollama), merged by reciprocal rank fusion. Each build is written to its own
folder under data/library/index/ and swapped in only when complete; build.json records the model.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from amocr.catalog import data_dir

OLLAMA = "http://127.0.0.1:11435"
MODEL = "bge-m3"
RRF_K = 60


def index_dir() -> Path:
    return data_dir() / "library" / "index"


def fold(text: str) -> str:
    """IAST or Devanagari → plain lower-case Latin letters for keyword search (ā→a, ś→s, ṃ→m …)."""
    from amocr.assemble import iast

    if re.search(r"[ऀ-ॿ]", text):
        text = iast(text)
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def embed(texts: list[str]) -> list[list[float]]:
    # Only the model and input: never num_ctx or keep_alive (they reload the model).
    req = urllib.request.Request(f"{OLLAMA}/api/embed", json.dumps({"model": MODEL, "input": texts}).encode(),
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=900))["embeddings"]


def all_units() -> list[dict]:
    """Every unit in the library: e-texts, plus assembled builds of OCR'd books (their latest build)."""
    from . import etext

    out = list(etext.units())
    for b in sorted((data_dir() / "works").glob("*/units")):
        builds = sorted(b.glob("v[0-9][0-9][0-9]"))
        if builds:
            out += [json.loads(ln) for ln in (builds[-1] / "units.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    return out


def build(batch: int = 64, log=print) -> dict:
    import lancedb
    import pyarrow as pa

    units = [u for u in all_units() if (u.get("text") or "").strip()]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = index_dir() / f"build-{stamp}"
    target.mkdir(parents=True)
    t0 = time.time()
    vecs: list[list[float]] = []
    for k in range(0, len(units), batch):
        vecs += embed([u["text"][:4000] for u in units[k:k + batch]])
        if (k // batch) % 20 == 0:
            log(f"  embedded {min(k + batch, len(units))}/{len(units)} ({time.time() - t0:.0f} s)")
    rows = [{"id": u["id"], "work": u["work"], "layer": u["layer"], "lang": u.get("lang", "san"),
             "status": u.get("status", ""), "search": fold(u.get("iast") or u["text"]), "vector": v}
            for u, v in zip(units, vecs)]
    db = lancedb.connect(str(target))
    schema = pa.schema([("id", pa.string()), ("work", pa.string()), ("layer", pa.string()), ("lang", pa.string()),
                        ("status", pa.string()), ("search", pa.string()), ("vector", pa.list_(pa.float32(), len(vecs[0])))])
    tbl = db.create_table("units", data=rows, schema=schema)
    tbl.create_fts_index("search")
    info = {"build": target.name, "date": stamp, "model": MODEL, "units": len(rows), "seconds": round(time.time() - t0),
            "works": sorted({u["work"] for u in units})}
    (target / "build.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    (index_dir() / "current").write_text(target.name, encoding="utf-8")       # swap in only when complete
    _table.cache_clear()
    return info


def add_work(wid: str, batch: int = 64, log=print) -> dict:
    """Put one work's units into the current index (replacing any it had): an import doesn't need a full
    rebuild. The build records what was added after it was made."""
    from . import etext

    tbl = _table()
    units = [u for u in etext.units(wid) if (u.get("text") or "").strip()]
    vecs: list[list[float]] = []
    for k in range(0, len(units), batch):
        vecs += embed([u["text"][:4000] for u in units[k:k + batch]])
        log(f"  embedded {min(k + batch, len(units))}/{len(units)}")
    if re.fullmatch(r"[\w.-]+", wid):
        tbl.delete(f"work = '{wid}'")
    tbl.add([{"id": u["id"], "work": u["work"], "layer": u["layer"], "lang": u.get("lang", "san"), "status": u.get("status", ""),
              "search": fold(u.get("iast") or u["text"]), "vector": v} for u, v in zip(units, vecs)])
    tbl.create_fts_index("search", replace=True)
    cur = index_dir() / (index_dir() / "current").read_text().strip()
    info = json.loads((cur / "build.json").read_text(encoding="utf-8"))
    info.setdefault("added", []).append({"work": wid, "units": len(units), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    (cur / "build.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return {"work": wid, "units": len(units)}


@lru_cache(maxsize=1)
def _table():
    import lancedb

    cur = index_dir() / "current"
    if not cur.exists():
        raise RuntimeError("no index yet: run `librarian build`")
    return lancedb.connect(str(index_dir() / cur.read_text().strip())).open_table("units")


def search(query: str, k: int = 10, work: str | None = None, layer: str | None = None) -> list[dict]:
    """Hybrid search: ids with their rank in each list and the fused score."""
    tbl = _table()
    where = " AND ".join(f"{c} = '{v}'" for c, v in (("work", work), ("layer", layer)) if v and re.fullmatch(r"[\w.-]+", v))
    pool = max(50, k * 5)
    kw, vec = [], []
    folded = fold(query)
    if folded:
        q = tbl.search(folded, query_type="fts").limit(pool)
        kw = [r["id"] for r in (q.where(where, prefilter=True) if where else q).to_list()]
    qv = tbl.search(embed([query])[0], vector_column_name="vector").limit(pool)
    vec = [r["id"] for r in (qv.where(where, prefilter=True) if where else qv).to_list()]
    scores: dict[str, dict] = {}
    for name, ids in (("keyword", kw), ("meaning", vec)):
        for rank, uid in enumerate(ids, 1):
            s = scores.setdefault(uid, {"id": uid, "score": 0.0})
            s["score"] += 1 / (RRF_K + rank)
            s[name] = rank
    return sorted(scores.values(), key=lambda x: -x["score"])[:k]
