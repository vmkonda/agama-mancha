"""Fix by instruction: the proofreader decides, a local model makes the edit.

In Proofread the person selects lines, types what to change ("the marker after योगी is २", "remove the
quotes", "षण्माससभ्यसेद् should be षण्मासमभ्यसेद्") and presses *Fix with local AI*. A worker on a machine
with Ollama (the Mac Studio; shared by every member, as local AI may be) turns the instruction into the
edited lines; they come back to the chat panel as proposals with *Apply*, exactly like Claude's. The
model never looks at the scan and never decides what is right: it only carries out the person's words.
Claude listeners and helpers never get these requests (chat.pending keeps them apart).

Server side: next_task / submit (GET /api/fix/next, POST /api/fix/answer). Worker: `amocr fix-worker`.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

MODEL = os.environ.get("AMOCR_FIX_MODEL", "qwen3.8:27b-mlx")
CLAIM_SECONDS = 180
_CLAIMS: dict[str, float] = {}           # message id -> when a worker took it
_LAST_POLL = [0.0]                       # when a worker last asked for work


def active() -> bool:
    """Is a local AI worker running (asked for work within the last minute)?"""
    return time.time() - _LAST_POLL[0] < 60

RULES = """You edit lines of a Sanskrit/Hindi book transcription exactly as a proofreader instructs.
- Change only what the instruction asks for. Copy every other character of every line exactly,
  including vowel signs, anusvara, virama, digits, danda (। ॥), spaces and punctuation.
- Never correct anything the instruction doesn't mention, even if it looks wrong to you: the text is
  transcribed as printed, misprints included.
- Return only the lines you changed, each as the whole new line, with its line number.
- If the instruction is unclear or doesn't fit the lines, change nothing and say why in `note`."""

SCHEMA = {"type": "object", "required": ["edits", "note"], "properties": {
    "edits": {"type": "array", "items": {"type": "object", "required": ["line", "to"], "properties": {
        "line": {"type": "integer"}, "to": {"type": "string"}}}},
    "note": {"type": "string"}}}


# ---- on the server -----------------------------------------------------------------------------

def next_task(works: dict, timeout: float = 25) -> dict | None:
    """The oldest instruction nobody has answered or taken, from any member (never a restricted book)."""
    from . import chat

    end = time.time() + timeout
    while True:
        now = _LAST_POLL[0] = time.time()
        for wid, work in works.items():
            if work.restricted or not chat.path(work).exists():
                continue
            for m in chat.pending(work, fixes=True):
                if now - _CLAIMS.get(m["id"], 0) < CLAIM_SECONDS or not (m.get("page") and m.get("n")):
                    continue
                n1, n2 = m["n"], m.get("n2") or m["n"]
                try:
                    lines = chat.range_context(work, m["page"], n1, n2)["lines"]
                except ValueError:
                    continue
                _CLAIMS[m["id"]] = now
                return {"work": wid, "id": m["id"], "page": m["page"], "instruction": m["text"],
                        "lines": [{"n": x["n"], "text": x["text"]} for x in lines]}
        if time.time() >= end:
            return None
        time.sleep(2)


def submit(works: dict, b: dict) -> dict:
    """A worker's edits: checked like any proposal (the page isn't verified, the line exists), and
    only lines that really change and were in the selection."""
    from . import chat

    work = works.get(str(b.get("work")))
    if not work or work.restricted:
        raise ValueError("no such book (or restricted)")
    q = next((m for m in chat.load(work) if m["id"] == str(b.get("id")) and m["role"] == "user" and m.get("kind") == "fix"), None)
    if not q:
        raise ValueError("no such instruction")
    if q["id"] not in {m["id"] for m in chat.pending(work, fixes=True)}:
        raise ValueError("already answered")
    n1, n2 = q["n"], q.get("n2") or q["n"]
    actions, skipped = [], 0
    for e in b.get("edits") or []:
        try:
            n = int(e.get("line"))
        except (TypeError, ValueError, AttributeError):
            skipped += 1
            continue
        if not n1 <= n <= n2:
            skipped += 1
            continue
        try:
            a = chat.check_action(work, {"type": "line", "page": q["page"], "n": n, "to": str(e.get("to", ""))})
        except ValueError as err:                 # a checked page, an empty line: say so instead of failing
            _CLAIMS.pop(q["id"], None)
            return chat.post(work, "ai", f"Nothing was changed: {err}.", reply_to=q["id"], model=str(b.get("model") or "")[:80])
        if a["to"] != a["from"]:
            actions.append(a)
    note = str(b.get("note") or "").strip()
    text = note or ("Here is the change, for you to check and apply." if actions else "No change was needed.")
    if skipped:
        text += f" ({skipped} edit(s) outside the selected lines were left out.)"
    _CLAIMS.pop(q["id"], None)
    return chat.post(work, "ai", text, reply_to=q["id"], actions=actions or None, model=str(b.get("model") or "")[:80])


# ---- the worker ------------------------------------------------------------------------------------

def edit(task: dict, model: str = MODEL, ollama: str | None = None) -> dict:
    """Ask the local model for the edited lines."""
    from librarian.index import OLLAMA

    shown = "\n".join(f"{x['n']}: {x['text']}" for x in task["lines"])
    prompt = f"{RULES}\n\nThe lines (number: text):\n{shown}\n\nThe proofreader's instruction:\n{task['instruction']}"
    body = {"model": model, "stream": False, "format": SCHEMA, "think": False, "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"{(ollama or OLLAMA).rstrip('/')}/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=600))
    return json.loads(r["message"]["content"])


def run(server: str, token: str | None = None, model: str = MODEL, once: bool = False, log=print) -> int:
    """Answer instructions until stopped (or, with once, until none is waiting)."""
    from librarian import remote

    log(f"local AI fixes for {server} with {model}")
    done = 0
    while True:
        t = remote.call_waiting(server, "/api/fix/next", token, log=log, query={"timeout": 2 if once else 25}, timeout=60).get("task")
        if not t:
            if once:
                return done
            continue
        start = time.time()
        try:
            out = edit(t, model)
            body = {"work": t["work"], "id": t["id"], "edits": out.get("edits") or [], "note": out.get("note", ""), "model": model}
        except Exception as e:  # noqa: BLE001  (a model or Ollama failure becomes an answer the person sees)
            body = {"work": t["work"], "id": t["id"], "edits": [], "model": model,
                    "note": f"The local AI couldn't make this change ({str(e)[:160]}). Try rewording it, or make it by hand."}
        try:
            r = remote.call(server, "/api/fix/answer", token, body=body)
            done += 1
            log(f"  {t['work']} p{t['page']}: {len(r.get('actions') or [])} line(s) proposed in {time.time() - start:.0f}s")
        except SystemExit as e:
            log(f"  {t['work']} p{t['page']}: not accepted ({e})")
