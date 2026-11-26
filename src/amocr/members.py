"""Members of a hosted Agama Mancha, and who is making the current request.

Hosted mode (`amocr serve --hosted`) admits only members: each has a personal token, stored here only
as a hash. A browser signs in once with its link (/login?token=…), which sets a cookie; a listener on a
member's machine sends the token as `Authorization: Bearer …`. Inside a request, `who()` is the member;
outside one (the local app, the command line) it is the machine's configured operator, as before.

The real deployment puts a gate in front of the server (Cloudflare Access or Tailscale, docs/plan.md);
these tokens are the app's own layer behind it, and enough on their own for a trial on a home network.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .catalog import data_dir

ROLES = ("reader", "proofreader", "validator", "coordinator", "admin")
_CURRENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("member", default=None)


def path() -> Path:
    return data_dir() / "hosted" / "members.json"


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load() -> dict:
    p = path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"members": {}}


def save(d: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(d, indent=1), encoding="utf-8")


def add(name: str, role: str = "proofreader") -> str:
    """Add (or re-issue) a member; returns their new token, shown once."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("a member needs a name (up to 80 characters)")
    token = "am_" + secrets.token_urlsafe(32)
    d = load()
    d["members"][name] = {"role": role, "token_sha256": _h(token),
                          "added": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    save(d)
    return token


def remove(name: str) -> bool:
    d = load()
    gone = d["members"].pop(name, None) is not None
    save(d)
    return gone


def check(token: str | None) -> tuple[str, str] | None:
    """(name, role) for a valid token, else None. Constant-time comparison."""
    if not token:
        return None
    h = _h(token)
    for name, m in load()["members"].items():
        if hmac.compare_digest(h, m["token_sha256"]):
            return name, m["role"]
    return None


def set_current(name: str | None):
    return _CURRENT.set(name)


def reset_current(tok) -> None:
    _CURRENT.reset(tok)


def who() -> str:
    """The member making this request; outside a hosted request, the machine's operator."""
    cur = _CURRENT.get()
    if cur:
        return cur
    from . import config as cfgmod

    return cfgmod.load().operator
