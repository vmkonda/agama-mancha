"""Studying with Claude: a chat beside the reader, answered by the person's own Claude Code session.

As with the proofreading chat, the app can't call Claude (no API). Questions go into
data/library/study/chat.jsonl with the passage being read; the Claude session waits for them with
`librarian study wait` (which marks it as listening), reads the passage and whatever else it needs from
the library, and answers with `librarian study reply`, citing every passage it relies on. Cited unit
ids become links that open in the reader. The librarian's grounding rules apply: answers come from
the library's passages, not from general knowledge.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from amocr.catalog import data_dir

LISTEN_FRESH = 30
MAX_TEXT = 8000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def study_dir() -> Path:
    return data_dir() / "library" / "study"


def path() -> Path:
    return study_dir() / "chat.jsonl"


def load() -> list[dict]:
    p = path()
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.exists() else []


def post(role: str, text: str, unit: str | None = None, reply_to: str | None = None,
         cites: list[str] | None = None, by: str = "") -> dict:
    from . import store

    if role not in ("user", "claude"):
        raise ValueError("bad role")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty message")
    if len(text) > MAX_TEXT:
        raise ValueError(f"message longer than {MAX_TEXT} characters")
    bad = [c for c in cites or [] if not store.get(c, context=0)]
    if bad:
        raise ValueError(f"no such unit(s): {', '.join(bad)}; cite ids from the library")
    msg = {"id": f"{int(time.time() * 1000):x}{secrets.token_hex(2)}", "at": _now(), "role": role, "text": text}
    for k, v in (("unit", unit), ("reply_to", reply_to), ("cites", cites or None), ("by", by or None)):
        if v:
            msg[k] = v
    study_dir().mkdir(parents=True, exist_ok=True)
    with path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg


def pending() -> list[dict]:
    msgs = load()
    answered = {m.get("reply_to") for m in msgs if m["role"] == "claude"}
    return [m for m in msgs if m["role"] == "user" and m["id"] not in answered]


def _beat() -> Path:
    return study_dir() / "listening"


def listening() -> bool:
    p = _beat()
    return p.exists() and time.time() - p.stat().st_mtime < LISTEN_FRESH


def wait(timeout: float = 1800, poll: float = 2.0) -> dict | None:
    end = time.time() + timeout
    study_dir().mkdir(parents=True, exist_ok=True)
    try:
        while time.time() < end:
            _beat().write_text(_now(), encoding="utf-8")
            todo = pending()
            if todo:
                return todo[0]
            time.sleep(poll)
        return None
    finally:
        _beat().unlink(missing_ok=True)
