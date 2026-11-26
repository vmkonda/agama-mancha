"""Talking to a hosted Agama Mancha from a member's machine (the listener side). Every request goes out
from here to the server over HTTP(S) with the member's token; the server never connects in."""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Your server and token, kept in a private file on your own machine (chmod 600), never in the
# repository or a chat: AGAMA_SERVER=http://<the server's address>:8770 and AGAMA_TOKEN=am_…
CONFIG = Path.home() / ".config" / "agama-mancha" / "hosted.env"


def _file() -> dict:
    if not CONFIG.exists():
        return {}
    out = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k in ("AGAMA_SERVER", "AGAMA_TOKEN"):
            out[k] = v.strip().strip('"').strip("'")
    return out


def server(arg: str | None = None, hosted: bool = False) -> str | None:
    """--server, else AGAMA_SERVER, else (only with --hosted) the private config file. Without any of
    them the commands work on this machine's own library."""
    s = arg or os.environ.get("AGAMA_SERVER") or (_file().get("AGAMA_SERVER") if hosted else None)
    return s.rstrip("/") if s else None


def _token(arg: str | None = None) -> str:
    t = arg or os.environ.get("AGAMA_TOKEN") or _file().get("AGAMA_TOKEN")
    if not t:
        raise SystemExit(f"a hosted server needs your member token: --token, AGAMA_TOKEN, or {CONFIG}")
    return t


def check(base: str | None, token: str | None = None) -> str:
    """Can this machine reach the server, and does it accept the token? One line saying which; never
    shows the token."""
    import socket

    if not base:
        return f"no server set: put AGAMA_SERVER=http://<server address>:8770 in {CONFIG}"
    u = urllib.parse.urlparse(base)
    host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
    try:
        mine = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None)} | {"127.0.0.1", "::1"}
    except OSError:
        mine = {"127.0.0.1", "::1"}
    if host in mine:
        return (f"{host} is this machine's own address: put the server's address in {CONFIG} "
                "(on Windows: `ipconfig`, the IPv4 Address).")
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as e:
        if not (_blocked(e) and shutil.which("curl")):
            return (f"can't reach {host}:{port} ({e.__class__.__name__}). Is the server running, on the same "
                    "network, and allowed through its firewall?")
        # macOS blocks Python here but lets curl through: the calls below go through curl.
    try:
        r = call(base, "/api/librarian/study", token, timeout=10)
    except SystemExit as e:
        return f"reached {base}, but it refused: {e}"
    return f"connected to {base} as {r.get('me') or '(local server, no members)'}; " + \
        ("a listener is already active for you" if r.get("listening") else "no listener active yet")


def _blocked(e: BaseException) -> bool:
    """macOS's Local Network privacy refuses Python's connections to the home network with 'No route
    to host' (errno 65), while its own tools such as curl are allowed."""
    r = getattr(e, "reason", e)
    return sys.platform == "darwin" and isinstance(r, OSError) and r.errno == 65


def _via_curl(method: str, url: str, token: str, data: bytes | None, timeout: float) -> tuple[int, bytes]:
    """The same request through macOS's own curl. The token goes in curl's config on stdin, never on
    the command line (where other programs could read it)."""
    import subprocess
    import tempfile

    cfg = f'header = "Authorization: Bearer {token}"\nheader = "Content-Type: application/json"\n'
    args = ["curl", "-sS", "-m", str(int(timeout)), "-X", method, "--config", "-", "-w", "\n%{http_code}"]
    body_file = None
    if data is not None:
        body_file = tempfile.NamedTemporaryFile(delete=False)
        body_file.write(data); body_file.close()
        args += ["--data-binary", f"@{body_file.name}"]
    try:
        r = subprocess.run(args + [url], input=cfg.encode(), capture_output=True, timeout=timeout + 10)
    finally:
        if body_file:
            os.unlink(body_file.name)
    if r.returncode != 0:
        raise OSError(r.stderr.decode(errors="replace").strip() or f"curl failed ({r.returncode})")
    out, _, code = r.stdout.rpartition(b"\n")
    return int(code or 0), out


def call(base: str, path: str, token: str | None = None, body: dict | None = None, query: dict | None = None,
         timeout: float = 90) -> dict:
    url = f"{base}{path}" + (("?" + urllib.parse.urlencode(query)) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    tok = _token(token)
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error")
        except Exception:
            msg = e.reason
        raise SystemExit(f"{base}: {msg}") from None
    except (urllib.error.URLError, OSError) as e:
        if not (_blocked(e) and shutil.which("curl")):
            raise SystemExit(f"{base}: can't connect ({getattr(e, 'reason', e)})") from None
    code, out = _via_curl("POST" if body is not None else "GET", url, tok, data, timeout)
    try:
        payload = json.loads(out or b"{}")
    except ValueError:
        payload = {}
    if code >= 400:
        raise SystemExit(f"{base}: {payload.get('error') or f'HTTP {code}'}")
    return payload


def fetch(base: str, path: str, token: str | None = None, timeout: float = 120) -> bytes:
    """Download a file (a page image, say) from the server; the same macOS fallback through curl."""
    url = f"{base}{path}"
    tok = _token(token)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{base}: {e.code} for {path}") from None
    except (urllib.error.URLError, OSError) as e:
        if not (_blocked(e) and shutil.which("curl")):
            raise SystemExit(f"{base}: can't connect ({getattr(e, 'reason', e)})") from None
    code, out = _via_curl("GET", url, tok, None, timeout)
    if code >= 400:
        raise SystemExit(f"{base}: {code} for {path}")
    return out
