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
    first = {}
    for u in by_id.values():
        first.setdefault(u["work"], u["id"])
    return [{"id": w, "title": works.get(w, {}).get("title", w), "author": works.get(w, {}).get("author", ""),
             "kind": works.get(w, {}).get("kind", ""), "units": n, "first": first.get(w),
             "source": (works.get(w, {}).get("source") or "")[:160], "licence": (works.get(w, {}).get("licence") or "")[:120],
             "url": source_link(works.get(w, {})), "origin": works.get(w, {}).get("origin", ""),
             "added": (works.get(w, {}).get("added") or "")[:10]} for w, n in sorted(counts.items())]


def _book_of(wid: str) -> str | None:
    """The local book (B-…) holding a printed work's pages, for links to its scans."""
    from amocr.catalog import load_works, resolve

    works = load_works()
    b = resolve(works, wid)
    if b in works:
        return b
    sha = next((w.sha256 for w in load_works(include_merged=True).values() if w.id == wid), None)
    return next((w.id for w in works.values() if sha and w.sha256 == sha and w.id != wid), None)


def source_link(w: dict) -> str | None:
    """Where an e-text came from, on the web."""
    if w.get("kind") == "etext" and w.get("file") and w.get("origin", "GRETIL") == "GRETIL":
        return "https://gretil.sub.uni-goettingen.de/gretil/corpustei/" + w["file"]
    return None


def context(uid: str, chapter: str | None = None) -> dict | None:
    """The whole chapter a unit is in (or another chapter of its work), in reading order, with the
    commentary where the edition puts it: what a reader needs around a citation."""
    by_id, order, _, works = _load()
    u = by_id.get(uid)
    if not u:
        return None
    wid = u["work"]
    ch = chapter or u.get("chapter")
    in_work = [x for x in by_id.values() if x["work"] == wid]
    chapters: list[str] = []
    for x in in_work:
        c = str(x.get("chapter"))
        if c not in chapters:
            chapters.append(c)
    units = [cite(x) for x in in_work if str(x.get("chapter")) == str(ch)]
    w = works.get(wid, {"id": wid, "title": wid})
    i = chapters.index(str(ch)) if str(ch) in chapters else -1
    out = {"work": {k: w.get(k) for k in ("id", "title", "author", "kind", "source", "licence", "origin", "added", "sha256")},
           "source_url": source_link(w), "chapter": str(ch), "chapters": chapters,
           "prev": chapters[i - 1] if i > 0 else None, "next": chapters[i + 1] if 0 <= i < len(chapters) - 1 else None,
           "target": uid if str(u.get("chapter")) == str(ch) else None, "units": units}
    if any(x.get("pages") for x in units):
        out["book"] = _book_of(wid)
        for x, raw in zip(units, [y for y in in_work if str(y.get("chapter")) == str(ch)]):
            if raw.get("lines"):
                x["lines"] = raw["lines"]
    return out

