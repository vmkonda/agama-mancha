"""Chat between a proofreader in the viewer and their own Claude Code session.

There is no API: the viewer can't call Claude. Messages go into data/works/<book>/chat.jsonl;
the volunteer's Claude session waits for them with `amocr chat wait` (which also marks it as
listening), answers with `amocr chat reply`, and waits again.

Claude's answers can carry actions, which the person applies (or not) in the viewer:
  {"type": "line", "page": 240, "n": 12, "from": "...", "to": "..."}  replace the nth line of text
  {"type": "rule", "id": "r1a2b3c4d"}                                   review a rule in Suggestions
Claude never changes page text itself.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import Work
from . import patterns as pat

LISTEN_FRESH = 30  # seconds: a heartbeat newer than this means Claude is listening
MAX_TEXT = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(work: Work) -> Path:
    return work.workdir / "chat.jsonl"


def load(work: Work) -> list[dict]:
    p = path(work)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _append(work: Work, msg: dict) -> dict:
    p = path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg


def post(work: Work, role: str, text: str, page: int | None = None, n: int | None = None,
         reply_to: str | None = None, actions: list[dict] | None = None) -> dict:
    if role not in ("user", "claude", "system"):
        raise ValueError("bad role")
    text = (text or "").strip()
    if not text and not actions:
        raise ValueError("empty message")
    if len(text) > MAX_TEXT:
        raise ValueError(f"message longer than {MAX_TEXT} characters")
    msg = {"id": f"{int(time.time() * 1000):x}{secrets.token_hex(2)}", "at": _now(), "role": role, "text": text}
    for k, v in (("page", page), ("n", n), ("reply_to", reply_to), ("actions", actions)):
        if v is not None:
            msg[k] = v
    return _append(work, msg)


def pending(work: Work) -> list[dict]:
    """The person's messages that have no reply yet, oldest first."""
    msgs = load(work)
    answered = {m.get("reply_to") for m in msgs if m["role"] == "claude"}
    return [m for m in msgs if m["role"] == "user" and m["id"] not in answered]


def applied(work: Work) -> set[str]:
    return {f"{m['applies']}:{m['action']}" for m in load(work) if m["role"] == "system" and "applies" in m}


# ---- listening -------------------------------------------------------------------------

def _beat_path(work: Work) -> Path:
    return work.workdir / "chat.listening"


def heartbeat(work: Work) -> None:
    _beat_path(work).write_text(_now(), encoding="utf-8")


def stop_listening(work: Work) -> None:
    _beat_path(work).unlink(missing_ok=True)


def listening(work: Work) -> bool:
    p = _beat_path(work)
    return p.exists() and time.time() - p.stat().st_mtime < LISTEN_FRESH


def wait(work: Work, timeout: float = 1800, poll: float = 2.0) -> dict | None:
    """Block until the person sends a message (returns the oldest unanswered one) or timeout."""
    end = time.time() + timeout
    try:
        while time.time() < end:
            heartbeat(work)
            todo = pending(work)
            if todo:
                return todo[0]
            time.sleep(poll)
        return None
    finally:
        stop_listening(work)


# ---- context and actions ---------------------------------------------------------------

def line_context(work: Work, page: int, n: int) -> dict:
    """The nth line of text on a page as it stands now, with its box and a saved crop of the scan."""
    d = pat.draft(work, page)
    if not d:
        raise ValueError(f"p{page}: no text yet")
    i = pat.line_index(d["text"], n)
    if i is None:
        raise ValueError(f"p{page} has no line {n}")
    box = d["boxes"][n - 1] if n - 1 < len(d["boxes"]) else None
    out = {"page": page, "n": n, "text": d["text"].split("\n")[i], "source": d["source"], "verified": d["verified"], "bbox": box}
    img = work.page_dir(page) / "image.png"
    if box and img.exists():
        from PIL import Image

        crop = work.workdir / "claude" / "ask" / f"p{page:04d}-l{n:02d}.png"
        crop.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(img) as im:
            im.crop((max(0, box[0] - 8), max(0, box[1] - 8), min(im.width, box[2] + 8), min(im.height, box[3] + 8))).save(crop)
        out["image"] = str(crop)
    return out


def check_action(work: Work, a: dict) -> dict:
    if a.get("type") == "line":
        page, n, to = int(a["page"]), int(a["n"]), str(a["to"]).strip()
        if not to:
            raise ValueError("a line fix needs the whole new line")
        ctx = line_context(work, page, n)
        if ctx["verified"]:
            raise ValueError(f"p{page} is verified; ask the person to change it in Proofread")
        return {"type": "line", "page": page, "n": n, "from": ctx["text"], "to": to}
    if a.get("type") == "rule":
        if not any(r["id"] == a.get("id") for r in pat.load(work)["rules"]):
            raise ValueError(f"no rule {a.get('id')!r}; add it with `amocr rule add` first")
        return {"type": "rule", "id": a["id"]}
    raise ValueError("action type must be line or rule")


def apply(work: Work, msg_id: str, index: int) -> dict:
    """The person pressed Apply on a line fix in a Claude message."""
    msg = next((m for m in load(work) if m["id"] == msg_id and m["role"] == "claude"), None)
    if not msg or not 0 <= index < len(msg.get("actions", [])):
        raise LookupError("no such suggestion")
    if f"{msg_id}:{index}" in applied(work):
        raise ValueError("already applied")
    a = msg["actions"][index]
    if a["type"] != "line":
        raise ValueError("only line fixes are applied here; rules go through Suggestions")
    d = pat.draft(work, a["page"])
    if not d or d["verified"]:
        raise ValueError(f"p{a['page']} is verified or has no text")
    lines = d["text"].split("\n")
    i = pat.line_index(d["text"], a["n"])
    if i is None or lines[i] != a["from"]:
        raise ValueError(f"p{a['page']} line {a['n']} has changed since Claude suggested this")
    lines[i] = a["to"]
    pat.write_draft(work, a["page"], d, lines, "chat_fixes_applied")
    note = {"id": f"{int(time.time() * 1000):x}{secrets.token_hex(2)}", "at": _now(), "role": "system",
            "text": f"applied to p{a['page']} line {a['n']}", "applies": msg_id, "action": index}
    _append(work, note)
    return {"page": a["page"], "n": a["n"]}
