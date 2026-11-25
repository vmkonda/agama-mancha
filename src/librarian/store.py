"""Reading passages from the library (never from the index): a unit, what explains it, its neighbours."""

from __future__ import annotations

import json
from functools import lru_cache

from . import etext
from .index import all_units


@lru_cache(maxsize=1)
def _load() -> tuple[dict, dict, dict, dict]:
    units = all_units()
    by_id = {u["id"]: u for u in units}
    order = {u["id"]: i for i, u in enumerate(units)}
    explained: dict[str, list[str]] = {}
    for u in units:
        for target in u.get("explains") or []:
            explained.setdefault(target, []).append(u["id"])
    works = {w["id"]: w for w in etext.works()}
    from amocr.catalog import load_works

    for w in load_works(include_merged=True).values():          # OCR'd books cited by their SL- id
        if w.origin == "repo":
            works.setdefault(w.id, {"id": w.id, "title": w.title, "kind": "ocr", "source": w.extra.get("commentary", "")})
    return by_id, order, explained, works


def reload() -> None:
    _load.cache_clear()


def work(wid: str) -> dict:
    return _load()[3].get(wid, {"id": wid, "title": wid})


def cite(u: dict) -> dict:
    """What a citation needs: id, work title, edition/source, position, status, and the text."""
    w = work(u["work"])
    out = {"id": u["id"], "work": u["work"], "title": w.get("title"), "chapter": u.get("chapter"), "verse": u.get("verse"),
           "layer": u.get("layer"), "lang": u.get("lang"), "status": u.get("status"),
           "edition": w.get("source", "")[:200] or w.get("kind", ""), "text": u.get("text"), "iast": u.get("iast")}
    if u.get("pages"):
        out["pages"] = u["pages"]                                # printed-book units: where on the scans
    if u.get("explains"):
        out["explains"] = u["explains"]
    return out


def get(uid: str, context: int = 1) -> dict | None:
    by_id, order, explained, _ = _load()
    u = by_id.get(uid)
    if not u:
        return None
    ids = list(by_id)
    i = order[uid]
    near = [ids[j] for j in range(max(0, i - context), min(len(ids), i + context + 1)) if j != i and by_id[ids[j]]["work"] == u["work"]]
    return cite(u) | {"commentary": [cite(by_id[c]) for c in explained.get(uid, [])][:6], "neighbours": near}


def catalog() -> list[dict]:
    by_id, _, _, works = _load()
    counts: dict[str, int] = {}
    for u in by_id.values():
        counts[u["work"]] = counts.get(u["work"], 0) + 1
    return [{"id": w, "title": works.get(w, {}).get("title", w), "author": works.get(w, {}).get("author", ""),
             "kind": works.get(w, {}).get("kind", ""), "units": n} for w, n in sorted(counts.items())]
