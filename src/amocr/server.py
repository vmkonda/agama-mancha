"""Local side-by-side viewer: page image next to OCR output, diff, and ground-truth editing.

Binds to 127.0.0.1 only. The scans and text are copyrighted; this never publishes them.
"""

from __future__ import annotations

import difflib
import getpass
import json
import os
import re
import socket
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlparse

from . import config as cfgmod
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

    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts:
                return self._send(files("amocr").joinpath("viewer.html").read_bytes(), "text/html; charset=utf-8")
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
                return self._json({"page": page, "results": res})
            if parts[0] == "api" and len(parts) == 4 and parts[3] == "diff":
                work, page = self._work_page(parts[1:3])
                q = parse_qs(url.query)
                res = _results(work, page)
                a, b = q.get("a", [""])[0], q.get("b", [""])[0]
                if a not in res or b not in res:
                    return self._err("unknown result label")
                return self._json({"ops": _diff(res[a]["text"], res[b]["text"]), "cer": round(cer(res[a]["text"], res[b]["text"]), 4)})
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
        except (ValueError, IndexError, FileNotFoundError) as e:
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
        if parts[2:] == ["patterns", "mine"]:
            data = pat.merge_mined(work, include_claude=bool(body.get("include_claude")))
            return self._json({"rules": len(data["rules"])})
        if len(parts) == 5 and parts[2] == "patterns" and parts[4] == "enabled":
            pat.set_enabled(work, parts[3], bool(body.get("enabled")))
            return self._json({"ok": True})
        if parts[2:] == ["chat"]:
            from . import chat

            page, n = body.get("page"), body.get("n")
            m = chat.post(work, "user", str(body.get("text", "")), page=int(page) if page else None, n=int(n) if n else None)
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

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[2] in ("patterns", "suggestions", "chat"):
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
            text, verified = body["text"], bool(body.get("verified"))
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            path = _gt_path(work, page)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
            # Who reviewed it and whether they checked every line against the print.
            path.with_suffix(".meta.json").write_text(json.dumps({
                "reviewer": cfgmod.load().operator, "verified": verified,
                "note": str(body.get("note", ""))[:2000],
                "saved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            self._json({"saved": str(path)})
        except LookupError as e:
            self._err(str(e), HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            self._err(str(e))


def serve(port: int = 8791, open_browser: bool = True, page: str | None = None) -> None:
    Handler.works = load_works()
    # macOS lets us bind 127.0.0.1:port even when another process holds *:port,
    # and requests may then reach that other process. Refuse instead.
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"port {port} is already in use by another process; pass --port")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/" + (f"#{page}" if page else "")
    print(f"amocr viewer at {url}  (Ctrl-C to stop)", flush=True)
    if os.environ.get("SSH_CONNECTION"):
        # Running over SSH: the browser is on the other machine. Never bind wider; tunnel instead.
        print(
            "SSH session detected. On the machine you're browsing from, run\n"
            f"  ssh -N -L {port}:127.0.0.1:{port} {getpass.getuser()}@{socket.gethostname()}\n"
            "(use whatever host name you normally ssh to), then open\n"
            f"  http://localhost:{port}/" + (f"#{page}" if page else "") + "\n"
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
