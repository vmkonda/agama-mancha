"""Asking a person for help with a line (Proofread → Ask someone).

A proofreader unsure of a line asks one or more named members ("ी or ो here?"). The people asked see
it in the title band on every page (Asked for help: N), open the line from there, and answer on it:
words, and optionally the line as they read it. An answer never changes the text: the person who
asked applies a suggested reading or not, as with every other suggestion, and they in turn see
"Answers: N" until they've read them. The person who asked closes the question when it's settled.

One file per book: data/works/<id>/help.json, changed only under a lock. Lines are numbered as in
Proofread (the Nth line of text); the line's text when asked is kept, so a later edit shows.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Work

_LOCK = threading.Lock()
MAX_TEXT = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(work: Work) -> Path:
    return work.workdir / "help.json"


def _load(work: Work) -> list[dict]:
    p = path(work)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(work: Work, items: list[dict]) -> None:
    p = path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _clean(text: str, what: str) -> str:
    text = str(text or "").strip()
    if not text:
        raise ValueError(f"{what} is empty")
    return text[:MAX_TEXT]


def ask(work: Work, page: int, n: int, question: str, by: str, to: list[str], line: str = "",
        members: set[str] | None = None) -> dict:
    """A question about line n of a page, for the named people. `members`: who exists (hosted)."""
    names = sorted({str(t).strip() for t in to if str(t).strip()} - {by})
    if not names:
        raise ValueError("ask at least one other person")
    if members is not None and (unknown := [t for t in names if t not in members]):
        raise ValueError(f"not members: {', '.join(unknown)}")
    if page < 1 or n < 1:
        raise ValueError("which page and line?")
    item = {"id": secrets.token_hex(6), "page": int(page), "n": int(n), "line": str(line)[:MAX_TEXT],
            "question": _clean(question, "the question"), "by": by, "to": names, "at": _now(),
            "status": "open", "answers": [], "seen_by_asker": True}
    with _LOCK:
        items = _load(work)
        items.append(item)
        _save(work, items)
    return item


def answer(work: Work, qid: str, by: str, text: str, reading: str = "") -> dict:
    """An answer on the line: words, and optionally the whole line as the person reads it."""
    with _LOCK:
        items = _load(work)
        q = next((x for x in items if x["id"] == qid), None)
        if not q:
            raise LookupError("no such question")
        if q["status"] == "closed":
            raise ValueError("that question is closed")
        q["answers"].append({"by": by, "text": _clean(text, "the answer"), "reading": str(reading or "").strip()[:MAX_TEXT],
                             "at": _now()})
        q["status"] = "answered"
        q["seen_by_asker"] = q["by"] == by
        _save(work, items)
    return q


def close(work: Work, qid: str, by: str) -> dict:
    """Settled: only the person who asked closes it."""
    with _LOCK:
        items = _load(work)
        q = next((x for x in items if x["id"] == qid), None)
        if not q:
            raise LookupError("no such question")
        if by != q["by"]:
            raise PermissionError("only the person who asked closes a question")
        q.update(status="closed", closed_at=_now(), seen_by_asker=True)
        _save(work, items)
    return q


def seen(work: Work, qid: str, by: str) -> None:
    """The person who asked has read the answers."""
    with _LOCK:
        items = _load(work)
        q = next((x for x in items if x["id"] == qid), None)
        if q and q["by"] == by and not q["seen_by_asker"]:
            q["seen_by_asker"] = True
            _save(work, items)


def on_page(work: Work, page: int) -> list[dict]:
    """Every question on a page that isn't closed, for Proofread."""
    return [x for x in _load(work) if x["page"] == page and x["status"] != "closed"]


def for_person(works: dict, who: str) -> dict:
    """What the title band shows a person: questions asked of them still waiting for their answer,
    and their own questions with answers they haven't read."""
    asked, answered = [], []
    for w in works.values():
        for q in _load(w):
            if q["status"] == "closed":
                continue
            row = {"work": w.id, "title": w.title} | {k: q[k] for k in ("id", "page", "n", "question", "by", "to", "at", "status")}
            if who in q["to"] and not any(a["by"] == who for a in q["answers"]):
                asked.append(row)
            if q["by"] == who and not q["seen_by_asker"]:
                answered.append(row | {"answers": len(q["answers"])})
    return {"asked": sorted(asked, key=lambda r: r["at"]), "answered": sorted(answered, key=lambda r: r["at"])}
