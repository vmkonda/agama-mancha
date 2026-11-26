"""The Claude helper: a file a member downloads from their Account page and double-clicks. It runs their own
Claude Code on their own machine, answering their questions from the proofreading and study panels.

The server does the thinking about *what* to ask: for each pending question it builds a complete task
(instructions, the material, links to the images, the shape of the answer), so improving the prompts
here reaches every helper without a new download. The helper only fetches a task, downloads its images,
runs `claude -p` (allowed to read those images and nothing else), and posts the structured answer back.
Restricted books are never handed out. Each download carries a fresh token for its member.
"""

from __future__ import annotations

import time
from importlib.resources import files

READING_RULES = """You are checking OCR of a printed Sanskrit/Hindi book against an image of the printed lines.
Rules (they matter more than speed):
- Transcribe what is printed, never what the text "should" say. Misprints, nonstandard sandhi and odd
  spellings stay as printed; mention a likely misprint in your answer instead of correcting it.
- A letter printed in a shape that resembles another is still that letter: in this edition's typeface the
  vowel sign ी can look like ो, and आ like भा or बा; write ी and आ where that is the letter.
- Footnote markers are small digits after a word (योगी२): keep them as digits. Devanagari digits look like
  letters (२ like र): don't confuse them.
- Keep daṇḍas (। ॥), verse numbers, hyphenated line breaks and punctuation as printed.
- Propose a fix only for a line that differs from the print: the whole corrected line. If you are unsure,
  say so in the answer and propose nothing for that line.
Answer briefly, in the language the question itself is written in (not the language of the book)."""

LIBRARIAN_RULES = """You are the librarian of a closed library of Śaiva and Trika texts. Answer only from the passages
given below; never from general knowledge. Rules:
- Quote the original (Devanagari or IAST) with your translation beneath it; flag loosely translated terms.
- Cite every passage you rely on by its id, in `cites`.
- When sources disagree, show each with its work; don't merge them.
- If the passages don't answer the question, say so and name the nearest works.
- Passages marked draft are unproofread OCR: say so when you rely on one.
Answer in the language the question itself is written in (not the language of the texts)."""

PROOF_SCHEMA = {"type": "object", "required": ["answer", "fixes"], "properties": {
    "answer": {"type": "string"},
    "fixes": {"type": "array", "items": {"type": "object", "required": ["page", "line", "to"], "properties": {
        "page": {"type": "integer"}, "line": {"type": "integer"}, "to": {"type": "string"}}}}}}
STUDY_SCHEMA = {"type": "object", "required": ["answer", "cites"], "properties": {
    "answer": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}


def _brief(work) -> str:
    from . import brief as briefmod

    p = briefmod.brief_path(work)
    return p.read_text(encoding="utf-8")[:4000] if p.exists() else ""


def _proof_task(work, m: dict) -> dict:
    from . import chat

    lines, images = [], []
    try:
        if m.get("page") and m.get("n"):
            ctx = chat.range_context(work, m["page"], m["n"], m.get("n2") or m["n"])
            lines = ctx["lines"]
            if ctx.get("image"):
                from pathlib import Path

                images.append(f"/api/{work.id}/chat/image/{Path(ctx['image']).name}")
    except ValueError:
        pass
    shown = "\n".join(f"page {m['page']} line {x['n']}: {x['text']}" for x in lines) or "(no line selected)"
    brief = _brief(work)
    prompt = (READING_RULES + (f"\n\nAbout this book (its brief):\n{brief}" if brief else "")
              + f"\n\nThe proofreader asks: {m['text']}\n\nThe line(s) as they stand now:\n{shown}\n"
              + ("\nThe printed line(s) are in the image file {IMAGE1}: read it and compare letter by letter.\n" if images else "")
              + "\nReturn your answer and any fixes (page, line, the whole corrected line).")
    where = f"page {m['page']}" + (f", line {m['n']}" if m.get("n") else "") if m.get("page") else "the chat"
    return {"kind": "proofread", "work": work.id, "id": m["id"], "summary": f"{work.title}, {where}",
            "prompt": prompt, "images": images, "schema": PROOF_SCHEMA}


def _study_task(m: dict) -> dict:
    from librarian import index, store

    focus = store.get(m["unit"], context=1) if m.get("unit") else None
    seen, parts = set(), []

    def add(u, label):
        if u and u["id"] not in seen:
            seen.add(u["id"])
            parts.append(f"[{u['id']}] {label}{u.get('title')} {u.get('chapter')}.{u.get('verse')} ({u.get('layer')}, {u.get('status')})\n"
                         f"{u.get('text')}" + (f"\n{u['iast']}" if u.get("iast") and u.get("lang") == "san" else ""))
    if focus:
        add(focus, "THE PASSAGE ASKED ABOUT: ")
        for c in focus.get("commentary", [])[:6]:
            add(c, "commentary on it: ")
        for nid in focus.get("neighbours", [])[:4]:
            add(store.get(nid, context=0), "next to it: ")
    try:
        for h in index.search(m["text"] + " " + (focus or {}).get("iast", ""), k=6):
            add(store.get(h["id"], context=0), "related: ")
    except Exception:
        pass
    quote = f"\nThe words they selected: «{m['quote']}»" if m.get("quote") else ""
    prompt = (LIBRARIAN_RULES + f"\n\nThe reader asks: {m['text']}{quote}\n\nPassages from the library:\n\n"
              + "\n\n".join(parts) + "\n\nReturn your answer and the ids you cite.")
    return {"kind": "study", "work": (focus or {}).get("work", ""), "id": m["id"],
            "summary": f"{(focus or {}).get('title', 'the library')}" + (f" {focus.get('chapter')}.{focus.get('verse')}" if focus else ""),
            "prompt": prompt, "images": [], "schema": STUDY_SCHEMA}


def next_task(works: dict, who: str | None, timeout: float = 25) -> dict | None:
    """This member's next unanswered question, proofreading first, then study; None after the timeout."""
    from . import chat

    try:
        from librarian import study
    except ImportError:
        study = None
    end = time.time() + timeout
    while True:
        if who:
            chat.polled(who)
            if study:
                study._LAST_POLL[who] = time.time()
        for wid, work in works.items():
            if work.restricted or not chat.path(work).exists():
                continue
            todo = chat.pending(work, who)
            if todo:
                return _proof_task(work, todo[0])
        if study:
            todo = study.pending(who)
            if todo:
                return _study_task(todo[0])
        if time.time() >= end:
            return None
        time.sleep(2)


def submit(works: dict, who: str | None, b: dict) -> dict:
    """A helper's answer: posted like a listener's reply, its fixes and citations checked here."""
    from . import chat

    kind, qid, answer = b.get("kind"), str(b.get("id") or ""), str(b.get("answer") or "").strip()
    if not answer:
        raise ValueError("an empty answer")
    if kind == "proofread":
        work = works.get(str(b.get("work")))
        if not work or work.restricted:
            raise ValueError("no such book (or restricted)")
        q = next((m for m in chat.load(work) if m["id"] == qid and m["role"] == "user"), None)
        if not q or (who and q.get("by") != who):
            raise ValueError("no such question of yours")
        actions = [chat.check_action(work, {"type": "line", "page": f.get("page"), "n": f.get("line"), "to": f.get("to")})
                   for f in b.get("fixes") or [] if isinstance(f, dict)]
        return chat.post(work, "claude", answer, reply_to=qid, actions=actions or None)
    if kind == "study":
        from librarian import store, study

        q = next((m for m in study.load() if m["id"] == qid and m["role"] == "user"), None)
        if not q or (who and q.get("by") != who):
            raise ValueError("no such question of yours")
        cites = [c for c in (b.get("cites") or []) if isinstance(c, str) and store.get(c, context=0)]
        return study.post("claude", answer, reply_to=qid, cites=cites, by="claude")
    raise ValueError("kind must be proofread or study")


def download(server_url: str, token: str) -> bytes:
    """The member's helper file: a Windows .cmd with this server and their fresh token inside."""
    ps = files("amocr").joinpath("helper.ps1").read_text(encoding="utf-8")
    ps = ps.replace("__SERVER__", server_url).replace("__TOKEN__", token)
    head = ("@echo off\r\n"
            "rem Agama Mancha: your Claude helper. Double-click to start; keep the window open while you work.\r\n"
            "powershell -NoProfile -ExecutionPolicy Bypass -Command \"$s=Get-Content -Raw -Encoding UTF8 '%~f0'; "
            "iex ($s -split '#{2}POWERSHELL#{2}')[-1]\"\r\n"
            "exit /b\r\n"
            "##POWERSHELL##\r\n")
    return (head + ps.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8")
