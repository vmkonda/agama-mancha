"""The Agama Mancha app: library, proofreading viewer, librarian.

By default it binds to 127.0.0.1 only: the scans and text are copyrighted and for Vimarsha's internal
use. Hosted mode (`--hosted`) serves members only: every request must carry a member's token (a
sign-in cookie or `Authorization: Bearer`), see members.py; it refuses to start without members.
"""

from __future__ import annotations

import difflib
import getpass
import json
import os
import re
import urllib.parse
from pathlib import Path
import socket
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from . import config as cfgmod
from . import members
from .catalog import Work, load_works
from .metrics import cer, normalize
from .pages import native_dpi, read_jsonl, render

GT = "groundtruth"


def _gt_path(work: Work, page: int):
    return work.gt_dir / f"p{page:04d}.txt"


def _results(work: Work, page: int) -> dict[str, dict]:
    out = {}
    for f in sorted((work.page_dir(page) / "ocr").glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = {
            k: rec.get(k)
            for k in ("text", "confidence", "engine", "engine_version", "config", "lines", "changes", "uncertain", "warnings", "created")
        }
    gt = _gt_path(work, page)
    if gt.exists():
        meta = gt.with_suffix(".meta.json")
        m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        out[GT] = {"text": gt.read_text(encoding="utf-8"), "engine": GT, "lines": None, "review": m}
    return out


def _pages(work: Work) -> list[dict]:
    inv = work.workdir / "inventory.jsonl"
    n = len(read_jsonl(inv)) if inv.exists() else 0
    rows = []
    for p in range(1, n + 1):
        d = work.page_dir(p)
        engines = sorted(f.stem for f in (d / "ocr").glob("*.json")) if d.exists() else []
        gt = _gt_path(work, p).exists()
        if engines or gt:
            rows.append({"page": p, "engines": engines, "groundtruth": gt})
    return rows


def _diff(a: str, b: str) -> list[list[str]]:
    """Character-level diff of normalized texts: [[op, a_part, b_part], ...]."""
    a, b = normalize(a), normalize(b)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [[op, a[i1:i2], b[j1:j2]] for op, i1, i2, j1, j2 in sm.get_opcodes()]


def _crop(work: Work, page: int, b: list[int], pad: int = 8) -> bytes:
    import io

    from PIL import Image

    img = work.page_dir(page) / "image.png"
    with Image.open(img) as im:
        c = im.crop((max(0, b[0] - pad), max(0, b[1] - pad), min(im.width, b[2] + pad), min(im.height, b[3] + pad)))
        buf = io.BytesIO()
        c.save(buf, format="PNG")
    return buf.getvalue()


# ---- the Library page: the shared catalog (docs/plan.md, phase A) -------------------

_refresh = {"running": False, "started": None, "result": None, "error": None}
_job = {"running": False, "what": None, "started": None, "result": None, "error": None}  # claim / release / fetch


def _library(works: dict[str, Work]) -> dict:
    from . import board, inventory, library

    cat = library.load()
    facts = inventory.merged()
    root = cat.get("root", "").rstrip("/")
    here = {w.remote: w.id for w in works.values() if w.remote}
    me = members.who()
    b = board.merge(board.load_all())
    entries = []
    for e in cat.get("entries", []):
        e = dict(e)
        if f"{root}/{e['path']}" in here:
            e["book"] = here[f"{root}/{e['path']}"]
        inv = inventory.short(facts.get(e.get("sha1") or ""))
        if inv:
            e["inv"] = inv
        x = b.get(e.get("sha1") or "")
        if x:
            p = x.get("progress") or {}
            e["board"] = {"holder": x.get("holder"), "since": x.get("since"), "stale": x.get("stale", False),
                          "stage": x["stage"], "stage_label": board.STAGE_LABEL[x["stage"]], "by": x.get("by"),
                          "progress": {k: p.get(k) for k in ("pages", "read", "claude", "proofread", "checked", "validated", "blank", "problem", "verified")}}
        entries.append(e)
    last = None
    log = library.local_dir() / "changes.jsonl"
    if log.exists():
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            last = {k: v for k, v in json.loads(lines[-1]).items() if k != "details"}
    age = library.age_hours(cat)
    return {"root": root, "refreshed_at": cat.get("refreshed_at"), "refreshed_by": cat.get("refreshed_by"),
            "age_hours": age, "count": cat.get("count", 0), "entries": entries, "last_change": last, "me": me,
            "stale_days": board.STALE_DAYS, "inventory": inventory.stats(cat, facts), "refresh": dict(_refresh), "job": dict(_job)}


def _background(state: dict, fn, **info) -> dict:
    import threading

    if state["running"]:
        return dict(state)

    def run():
        try:
            state["result"] = fn()
            state["error"] = None
        except BaseException as e:  # SystemExit from the Proton wrapper carries the reason
            state["error"] = str(e) or e.__class__.__name__
        finally:
            state["running"] = False

    state.update(running=True, started=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=None,
                 result=None, **info)
    threading.Thread(target=run, daemon=True).start()
    return dict(state)


def _start_refresh() -> dict:
    from . import library

    def go():
        return {k: v for k, v in library.refresh().items() if k != "details"}

    return _background(_refresh, go)


def _start_job(action: str, key: str, handler) -> dict:
    """Claim (and fetch the PDF if it isn't here), release, or sync the board, in the background."""
    from . import board, book, library

    def work_on():
        r = board.claim(key)
        if not r["ok"]:
            return r
        root = library.load().get("root", "").rstrip("/")
        remote = f"{root}/{r['entry']['path']}"
        if not any(w.remote == remote for w in handler.works.values()):
            w, _ = book.fetch(remote)
            handler.works = load_works()
            r["fetched"] = w.id
        board.refresh_board()
        return r

    fns = {"claim": work_on, "release": lambda: board.release(key), "sync": lambda: (board.refresh_board(), {"ok": True})[1]}
    if action not in fns:
        raise LookupError("not found")
    return _background(_job, lambda: {k: v for k, v in fns[action]().items() if k != "entry"}, what=f"{action} {key}".strip())


class Handler(BaseHTTPRequestHandler):
    works: dict[str, Work] = {}

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def _err(self, msg, status=HTTPStatus.BAD_REQUEST):
        self._json({"error": msg}, status)

    def _work_page(self, parts):
        work = self.works.get(parts[0]) if parts else None
        if not work:
            raise LookupError("unknown work")
        page = int(parts[1]) if len(parts) > 1 and re.fullmatch(r"\d{1,5}", parts[1]) else None
        return work, page

    hosted = False

    PUBLIC = {"/login", "/invite", "/theme.css", "/api/auth/login", "/api/auth/invite"}

    def _cookie(self, name: str) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _bearer(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        return auth[7:].strip() if auth.startswith("Bearer ") else None

    def _gate(self) -> bool:
        """Hosted mode: admit members only (a browser session, or a listener's token) and remember who
        this request is for. The sign-in pages are open. True = go ahead."""
        self._member = None
        if not self.hosted:
            return True
        url = urlparse(self.path)
        who = members.check_session(self._cookie("am_session")) or members.check(self._bearer())
        if who:
            self._member = who
            return True
        if url.path in self.PUBLIC:
            return True
        if url.path.startswith("/api/"):
            self._err("members only: sign in", HTTPStatus.UNAUTHORIZED)
        else:                                          # a page: to the sign-in page, then back here
            nxt = urllib.parse.quote(url.path + (("?" + url.query) if url.query else ""), safe="")
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", f"/login?next={nxt}")
            self.send_header("Content-Length", "0")
            self.end_headers()
        return False

    def _session_cookie(self, sid: str | None) -> str:
        if not sid:
            return "am_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
        return f"am_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={members.SESSION_DAYS * 86400}"

    def _auth_post(self, parts: list[str]) -> None:
        """Sign in, set a password from an invite, sign out, change password, issue a listener token."""
        try:
            b = self._body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._err(str(e))
        act = parts[2] if len(parts) == 3 else ""
        try:
            if act in ("login", "invite"):
                if act == "login":
                    who = members.verify(str(b.get("name", "")).strip(), str(b.get("password", "")))
                    if not who:
                        return self._err("wrong name or password", HTTPStatus.UNAUTHORIZED)
                    name = who[0]
                else:
                    name = members.use_invite(str(b.get("code", "")), str(b.get("password", "")))
                body = json.dumps({"ok": True, "name": name}).encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Set-Cookie", self._session_cookie(members.new_session(name)))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._member:
                return self._err("members only: sign in", HTTPStatus.UNAUTHORIZED)
            name = self._member[0]
            if act == "logout":
                members.end_session(self._cookie("am_session"))
                body = b'{"ok": true}'
                self.send_response(HTTPStatus.OK)
                self.send_header("Set-Cookie", self._session_cookie(None))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if act == "password":
                if not members.verify(name, str(b.get("current", ""))):
                    return self._err("the current password isn't right", HTTPStatus.UNAUTHORIZED)
                members.set_password(name, str(b.get("new", "")))
                return self._json({"ok": True})
            if act == "token":
                return self._json({"token": members.issue_token(name)})
        except PermissionError as e:
            return self._err(str(e), HTTPStatus.TOO_MANY_REQUESTS)
        except ValueError as e:
            return self._err(str(e))
        self._err("not found", HTTPStatus.NOT_FOUND)

    def do_GET(self):
        if not self._gate():
            return
        tok = members.set_current((self._member or (None,))[0])
        try:
            self._do_get()
        finally:
            members.reset_current(tok)

    def do_POST(self):
        if not self._gate():
            return
        tok = members.set_current((self._member or (None,))[0])
        try:
            self._do_post()
        finally:
            members.reset_current(tok)

    def _do_get(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts:
                # The home page is the Library. Old links to the viewer (/#book/page…) still work: the
                # part after # never reaches the server, so a tiny page forwards it to /proofread.
                return self._send(HOME, "text/html; charset=utf-8")
            if parts in (["login"], ["invite"], ["account"]):
                return self._send(files("amocr").joinpath("signin.html").read_bytes(), "text/html; charset=utf-8")
            if parts == ["api", "me"]:
                m = self._member
                return self._json({"hosted": self.hosted, "name": m[0] if m else None, "role": m[1] if m else None})
            if parts == ["proofread"]:
                return self._send(files("amocr").joinpath("viewer.html").read_bytes(), "text/html; charset=utf-8")
            if parts == ["library"]:
                return self._send(files("amocr").joinpath("library.html").read_bytes(), "text/html; charset=utf-8")
            if parts == ["librarian"]:
                return self._send(files("amocr").joinpath("librarian.html").read_bytes(), "text/html; charset=utf-8")
            if parts[:2] == ["api", "librarian"]:
                return self._json(_librarian_get(parts[2:], parse_qs(url.query)))
            if parts == ["me.js"]:
                return self._send(files("amocr").joinpath("me.js").read_bytes(), "text/javascript; charset=utf-8")
            if parts == ["theme.css"]:
                return self._send(files("amocr").joinpath("theme.css").read_bytes(), "text/css; charset=utf-8")
            if parts == ["api", "catalog"]:
                return self._json(_library(self.works))
            if parts == ["api", "works"]:
                return self._json([{"id": w.id, "title": w.title} for w in self.works.values()])
            if parts[0] == "api" and len(parts) == 3 and parts[2] == "pages":
                work, _ = self._work_page(parts[1:])
                return self._json(_pages(work))
            if parts[0] == "api" and len(parts) == 3 and parts[2] == "chat":
                from . import chat

                work, _ = self._work_page(parts[1:2])
                return self._json({"messages": chat.load(work)[-200:], "listening": chat.listening(work),
                                   "applied": sorted(chat.applied(work))})
            if parts[0] == "api" and len(parts) in (3, 4) and parts[2] == "grid":
                from . import grid

                work, _ = self._work_page(parts[1:2])
                if len(parts) == 4 and parts[3] == "warnings":
                    return self._json({str(k): v for k, v in grid.warnings(work).items()})
                return self._json(grid.pages(work))
            if parts[0] == "api" and len(parts) == 3 and parts[2] == "patterns":
                from . import patterns as pat

                work, _ = self._work_page(parts[1:2])
                data, n = pat.load(work), pat.counts(work)
                return self._json({"rules": [r | {"pending": n.get(r["id"], 0)} for r in data["rules"]],
                                   "decided": len(data["decisions"])})
            if parts[0] == "api" and len(parts) == 3 and parts[2] == "suggestions":
                from . import patterns as pat

                work, _ = self._work_page(parts[1:2])
                rule = parse_qs(url.query).get("rule", [None])[0] or None
                return self._json(pat.suggest(work, rule, limit=300))
            if parts[0] == "api" and len(parts) == 3:
                work, page = self._work_page(parts[1:])
                res = _results(work, page)
                ref = res.get(GT, {}).get("text")
                for label, r in res.items():
                    if ref is not None and label != GT:
                        r["cer"] = round(cer(r["text"], ref), 4)
                from . import ladder

                meta_path = _gt_path(work, page).with_suffix(".meta.json")
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
                me = members.who()
                ok, why = ladder.can_validate(meta, me)
                return self._json({"page": page, "results": res,
                                   "ladder": {"status": ladder.of(meta) if GT in res else "none", "me": me,
                                              "can_validate": ok, "why_not": why,
                                              "proofread_by": (meta or {}).get("proofread_by"),
                                              "validated_by": (meta or {}).get("validated_by")}})
            if parts[0] == "api" and len(parts) in (4, 5) and parts[3] == "history":
                from . import history

                work, page = self._work_page(parts[1:3])
                versions = history.load(work, page)
                base = history.base_text(work, page)
                if len(parts) == 4:
                    return self._json({"versions": [{k: v for k, v in x.items() if k != "text"} for x in versions],
                                       "base": base[0] if base else None})
                if parts[4] != "diff":
                    raise LookupError("not found")
                q = parse_qs(url.query)
                texts = {str(x["v"]): x["text"] for x in versions}
                if base:
                    texts["ocr"] = base[1]
                gt = work.gt_dir / f"p{page:04d}.txt"
                if versions:
                    texts["current"] = versions[-1]["text"]
                elif gt.exists():                                   # saved before history began
                    texts["current"] = gt.read_text(encoding="utf-8")
                a, b = q.get("a", [""])[0], q.get("b", [""])[0]
                if a not in texts or b not in texts:
                    return self._err("unknown version")
                return self._json({"ops": _diff(texts[a], texts[b]), "cer": round(cer(texts[a], texts[b]), 4)})
            if parts[0] == "api" and len(parts) == 4 and parts[3] == "diff":
                work, page = self._work_page(parts[1:3])
                q = parse_qs(url.query)
                res = _results(work, page)
                a, b = q.get("a", [""])[0], q.get("b", [""])[0]
                if a not in res or b not in res:
                    return self._err("unknown result label")
                return self._json({"ops": _diff(res[a]["text"], res[b]["text"]), "cer": round(cer(res[a]["text"], res[b]["text"]), 4)})
            if parts[0] == "brief" and len(parts) == 2:
                from . import brief

                work, _ = self._work_page(parts[1:2])
                p = brief.brief_path(work)
                body = p.read_text(encoding="utf-8") if p.exists() else f"No brief yet. In Claude Code: amocr brief {work.id} --sources"
                return self._send(body.encode(), "text/plain; charset=utf-8")
            if parts[0] == "crop" and len(parts) == 3:
                work, page = self._work_page(parts[1:])
                b = [int(float(x)) for x in parse_qs(url.query).get("b", [""])[0].split(",")]
                if len(b) != 4:
                    raise ValueError("b=x0,y0,x1,y1")
                return self._send(_crop(work, page, b), "image/png")
            if parts[0] == "img" and len(parts) == 3:
                work, page = self._work_page(parts[1:])
                img = work.page_dir(page) / "image.png"
                if not img.exists():
                    rows = read_jsonl(work.workdir / "inventory.jsonl")
                    render(work.source, page, img, native_dpi(rows[page - 1]))
                return self._send(img.read_bytes(), "image/png")
        except LookupError as e:
            return self._err(str(e), HTTPStatus.NOT_FOUND)
        except (ValueError, IndexError, FileNotFoundError, RuntimeError) as e:
            return self._err(str(e))
        self._err("not found", HTTPStatus.NOT_FOUND)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n > 2_000_000:
            raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _post_patterns(self, parts) -> None:
        """POST /api/<work>/patterns/mine | patterns/<rule>/enabled | suggestions/decide | chat | chat/apply"""
        from . import patterns as pat

        work, _ = self._work_page(parts[1:2])
        body = self._body()
        if parts[2:] == ["structure"]:      # the assembler's view of a page being proofread (read-only)
            from . import assemble

            text = body.get("text")
            if not isinstance(text, str) or len(text) > 200_000:
                raise ValueError("text: the page's text")
            return self._json(assemble.page_structure(work, int(body.get("page") or 0), text))
        if parts[2:] == ["patterns", "mine"]:
            data = pat.merge_mined(work, include_claude=bool(body.get("include_claude")))
            return self._json({"rules": len(data["rules"])})
        if len(parts) == 5 and parts[2] == "patterns" and parts[4] == "enabled":
            pat.set_enabled(work, parts[3], bool(body.get("enabled")))
            return self._json({"ok": True})
        if parts[2:] == ["chat"]:
            from . import chat

            page, n, n2 = body.get("page"), body.get("n"), body.get("n2")
            m = chat.post(work, "user", str(body.get("text", "")), page=int(page) if page else None, n=int(n) if n else None,
                          n2=int(n2) if n2 else None, kind="check" if body.get("kind") == "check" else None)
            return self._json(m)
        if parts[2:] == ["chat", "apply"]:
            from . import chat

            return self._json(chat.apply(work, str(body.get("msg", "")), int(body.get("index", -1))))
        if parts[2:] == ["suggestions", "decide"]:
            items = body.get("items") or []
            if not isinstance(items, list) or not items or len(items) > 500:
                raise ValueError("items: 1-500 suggestions")
            done = [pat.decide(work, it, bool(body.get("accept"))) for it in items]
            return self._json({"done": len(done)})
        raise LookupError("not found")

    def _do_post(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts[:2] == ["api", "auth"]:
            if not self.hosted:
                return self._err("signing in is only for a hosted server", HTTPStatus.NOT_FOUND)
            return self._auth_post(parts)
        if parts == ["api", "librarian", "import"]:
            try:
                _librarian()
                from librarian import importer

                n = int(self.headers.get("Content-Length", 0))
                if n > importer.MAX_UPLOAD + 100_000:
                    raise ValueError("file too large (20 MB at most)")
                b = json.loads(self.rfile.read(n) or b"{}")
                if b.get("gretil"):
                    return self._json(importer.from_gretil(str(b["gretil"]), str(b.get("title") or "") or None))
                up = b.get("upload") or {}
                if up.get("text"):
                    return self._json(importer.from_upload(str(up.get("name") or "upload.xml"), str(up["text"]),
                                                           *(str(up.get(k) or "") for k in ("title", "author", "licence", "source"))))
                raise ValueError("say what to import: a GRETIL file or an uploaded TEI file")
            except (ValueError, RuntimeError, json.JSONDecodeError) as e:
                return self._err(str(e))
        if parts == ["api", "librarian", "study", "reply"]:     # a listener's answer
            try:
                from librarian import study

                b = self._body()
                q = next((m for m in study.load() if m["id"] == str(b.get("reply_to"))), None)
                if not q or (Handler.hosted and q.get("by") != members.who()):
                    raise ValueError("no such question of yours")
                return self._json(study.post("claude", str(b.get("text", "")), reply_to=q["id"],
                                             cites=[str(c) for c in b.get("cites") or []], by="claude"))
            except (ValueError, RuntimeError, json.JSONDecodeError) as e:
                return self._err(str(e))
        if parts == ["api", "librarian", "study"]:
            try:
                _librarian()
                from librarian import study

                b = self._body()
                return self._json(study.post("user", str(b.get("text", "")), unit=str(b.get("unit") or "") or None,
                                             quote=str(b.get("quote") or "") or None, by=members.who() or ""))
            except (ValueError, RuntimeError, json.JSONDecodeError) as e:
                return self._err(str(e))
        if parts[:3] == ["api", "librarian", "eval"]:
            try:
                return self._json(_librarian_eval_post(parts[3:], self._body()))
            except LookupError as e:
                return self._err(str(e), HTTPStatus.NOT_FOUND)
            except (ValueError, RuntimeError, json.JSONDecodeError) as e:
                return self._err(str(e))
        if parts == ["api", "catalog", "refresh"]:
            return self._json(_start_refresh())
        if len(parts) == 3 and parts[:2] == ["api", "board"]:
            try:
                key = str(self._body().get("key", "")) if parts[2] != "sync" else ""
                if parts[2] != "sync" and not re.fullmatch(r"[0-9a-f]{40}", key):
                    raise ValueError("key: the book's SHA-1")
                return self._json(_start_job(parts[2], key, type(self)))
            except LookupError as e:
                return self._err(str(e), HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as e:
                return self._err(str(e))
        if len(parts) >= 3 and parts[0] == "api" and parts[2] in ("patterns", "suggestions", "chat", "structure"):
            try:
                return self._post_patterns(parts)
            except LookupError as e:
                return self._err(str(e), HTTPStatus.NOT_FOUND)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                return self._err(str(e))
        # Otherwise only writes ground truth for a known work and page: POST /api/<work>/<page>/groundtruth
        if not (len(parts) == 4 and parts[0] == "api" and parts[3] == GT):
            return self._err("not found", HTTPStatus.NOT_FOUND)
        try:
            work, page = self._work_page(parts[1:3])
            if page is None:
                raise ValueError("bad page")
            n = int(self.headers.get("Content-Length", 0))
            if n > 2_000_000:
                raise ValueError("too large")
            body = json.loads(self.rfile.read(n))
            from . import ladder

            text = body["text"]
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            # The page's status on the ladder (an older viewer sends only "verified").
            status = body.get("status") or ("proofread" if body.get("verified") else "draft")
            path = _gt_path(work, page)
            meta_path = path.with_suffix(".meta.json")
            old_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            # Check the step first (e.g. validating your own proofreading), so a refusal changes nothing.
            # Keep what's already recorded (the reading it started from, fixes applied).
            meta = ladder.change(old_meta, status, members.who(), str(body.get("note", ""))[:2000])
            if body.get("base") and not meta.get("base"):      # the reading the page started from
                meta["base"] = str(body["base"])[:200]
            from . import history

            history.record(work, page, text, meta, "save")       # every version is kept
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            self._json({"saved": str(path), "status": meta["status"]})
        except LookupError as e:
            self._err(str(e), HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self._err(str(e))


HOME = (b"<!doctype html><meta charset=utf-8><title>Agama Mancha</title>"
        b"<script>location.replace(location.hash ? '/proofread' + location.hash : '/library')</script>"
        b"<noscript><a href='/library'>Agama Mancha: the Library</a></noscript>")


def _librarian():
    """The librarian is an optional extra; say how to install it rather than failing obscurely."""
    try:
        from librarian import evals, index, store
    except ImportError as e:
        raise RuntimeError(f"the librarian isn't installed here ({e.name}): run `uv sync --extra librarian`") from None
    return evals, index, store


def _librarian_get(parts: list[str], q: dict) -> object:
    evals, index, store = _librarian()
    one = lambda k, d="": (q.get(k) or [d])[0]
    if parts == ["works"]:
        return store.catalog()
    if parts == ["search"]:
        query = one("q").strip()
        if not query:
            raise ValueError("q: what to search for")
        hits = index.search(query, k=min(int(one("k", "10") or 10), 50), work=one("work") or None, layer=one("layer") or None)
        out = []
        for h in hits:
            u = store.get(h["id"], context=0)
            if u:
                u.pop("neighbours", None)
                out.append(u | {"found_by": {x: h[x] for x in ("keyword", "meaning") if x in h},
                                "n_commentary": len(u.pop("commentary", []))})
        return out
    if parts == ["unit"]:
        return store.get(one("id"), context=2) or {"error": "no such unit"}
    if parts == ["gretil"]:
        from librarian import etext, gretil

        have = {w.get("file"): w["id"] for w in etext.works()}
        q = one("q").strip()
        items = gretil.search(q, limit=60) if q else gretil.catalogue()[:60]
        return {"total": len(gretil.catalogue()), "items": [x | {"imported": have.get(Path(x["path"]).name)} for x in items]}
    if parts == ["import"]:
        from librarian import importer

        return importer.status()
    if parts == ["study"]:
        from librarian import study

        me = members.who() if Handler.hosted else None
        return {"messages": study.thread(me)[-120:], "listening": study.listening(me), "me": me}
    if parts == ["study", "next"]:                     # a member's listener, long-polling for their questions
        from librarian import study

        m = study.wait(timeout=min(float(one("timeout", "25") or 25), 55), who=members.who() if Handler.hosted else None)
        return {"message": m, "context": store.get(m["unit"], context=2) if m and m.get("unit") else None}
    if parts == ["read"]:
        return store.context(one("id"), one("chapter") or None) or {"error": "no such unit"}
    if parts == ["eval"]:
        return {"questions": evals.load(), "types": evals.TYPES, "last_run": evals.last_run()}
    raise LookupError("not found")


def _librarian_eval_post(parts: list[str], body: dict) -> object:
    evals, _, _ = _librarian()
    if parts == ["run"]:
        return evals.run(only_approved=bool(body.get("only_approved")))
    if len(parts) == 1:
        return evals.update(parts[0], body, members.who() or "unknown")
    raise LookupError("not found")


def serve(port: int = 8791, open_browser: bool = True, page: str | None = None,
          host: str = "127.0.0.1", hosted: bool = False) -> None:
    Handler.works = load_works()
    Handler.hosted = hosted
    if host not in ("127.0.0.1", "localhost", "::1") and not hosted:
        raise SystemExit("refusing to serve beyond this machine without --hosted (members only): "
                         "the scans and text are for Vimarsha's internal use")
    if hosted and not members.load()["members"]:
        raise SystemExit('hosted mode needs members first: amocr member add "<name>" --role admin')
    # macOS lets us bind 127.0.0.1:port even when another process holds *:port,
    # and requests may then reach that other process. Refuse instead.
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"port {port} is already in use by another process; pass --port")
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/" + (f"proofread#{page}" if page else "")
    print(f"amocr viewer at {url}  (Ctrl-C to stop)", flush=True)
    if hosted:
        print(f"HOSTED, members only, listening on {host}:{port}. {len(members.load()['members'])} member(s). "
              "Plain HTTP: fine for a trial on a home network; a real deployment puts it behind HTTPS and a gate "
              "(docs/plan.md).", flush=True)
        open_browser = False
    elif os.environ.get("SSH_CONNECTION"):
        # Running over SSH: the browser is on the other machine. Never bind wider; tunnel instead.
        print(
            "SSH session detected. On the machine you're browsing from, run\n"
            f"  ssh -N -L {port}:127.0.0.1:{port} {getpass.getuser()}@{socket.gethostname()}\n"
            "(use whatever host name you normally ssh to), then open\n"
            f"  http://localhost:{port}/" + (f"proofread#{page}" if page else "") + "\n"
            f"Or add the tunnel to your open ssh session: press Enter, type ~C, then -L {port}:127.0.0.1:{port}",
            flush=True,
        )
        open_browser = False
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
