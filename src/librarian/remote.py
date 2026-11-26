"""Talking to a hosted Agama Mancha from a member's machine (the listener side). Every request goes out
from here to the server over HTTP(S) with the member's token; the server never connects in."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def server(arg: str | None = None) -> str | None:
    s = arg or os.environ.get("AGAMA_SERVER")
    return s.rstrip("/") if s else None


def _token(arg: str | None = None) -> str:
    t = arg or os.environ.get("AGAMA_TOKEN")
    if not t:
        raise SystemExit("a hosted server needs your member token: --token or AGAMA_TOKEN")
    return t


def call(base: str, path: str, token: str | None = None, body: dict | None = None, query: dict | None = None,
         timeout: float = 90) -> dict:
    url = f"{base}{path}" + (("?" + urllib.parse.urlencode(query)) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {_token(token)}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error")
        except Exception:
            msg = e.reason
        raise SystemExit(f"{base}: {msg}") from None
