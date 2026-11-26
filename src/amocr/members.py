"""Members of a hosted Agama Mancha: who they are, how they sign in, and who is making the current request.

- **Passwords** are stored only as salted scrypt hashes (never encrypted, never readable back), on the
  server only: `data/hosted/members.json`, never the shared drive (its editors could change the file).
- **Invites**: a new member gets a one-time link (7 days) to choose their password; a forgotten
  password is a new invite from the coordinator.
- **Sessions**: signing in sets a cookie holding a random session id; the server keeps only its hash
  (`data/hosted/sessions.json`, 30 days) and signing out ends it.
- **Listener tokens**: a member's Claude Code listener sends a personal token as `Authorization:
  Bearer …`; issued on request, revocable, stored as a hash.
- **Lockout**: five wrong passwords for a name lock it for a minute.

Inside a request, `who()` is the member; outside one (the local app, the command line) it is the
machine's configured operator. The real deployment also puts a gate in front (docs/plan.md).
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import data_dir

ROLES = ("reader", "proofreader", "validator", "coordinator", "admin")
INVITE_DAYS = 7
SESSION_DAYS = 30
MIN_PASSWORD = 10
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
_CURRENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("member", default=None)
_FAILS: dict[str, list[float]] = {}


def _dir() -> Path:
    return data_dir() / "hosted"


def path() -> Path:
    return _dir() / "members.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load() -> dict:
    p = path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"members": {}}


def save(d: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(path())


# ---- members and invites ------------------------------------------------------------------------

def add(name: str, role: str = "proofreader") -> str:
    """Add a member (or change their role); returns a one-time invite code to choose their password."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError("a member needs a name (up to 80 characters)")
    d = load()
    m = d["members"].setdefault(name, {"added": _now()})
    m["role"] = role
    save(d)
    return invite(name)


def invite(name: str) -> str:
    """A new one-time invite code for a member (to set or reset their password); 7 days."""
    d = load()
    if name not in d["members"]:
        raise ValueError(f"no member {name!r}")
    code = "inv_" + secrets.token_urlsafe(24)
    d["members"][name]["invite"] = {"sha256": _h(code), "expires": time.time() + INVITE_DAYS * 86400}
    save(d)
    return code


def remove(name: str) -> bool:
    d = load()
    gone = d["members"].pop(name, None) is not None
    save(d)
    end_sessions(name)
    return gone


# ---- passwords ----------------------------------------------------------------------------------

def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT).hex()


def _check_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"a password needs at least {MIN_PASSWORD} characters")


def set_password(name: str, password: str) -> None:
    _check_strength(password)
    d = load()
    if name not in d["members"]:
        raise ValueError(f"no member {name!r}")
    salt = secrets.token_bytes(16)
    d["members"][name]["password"] = {"scrypt": _hash_pw(password, salt), "salt": salt.hex(), **_SCRYPT}
    d["members"][name].pop("invite", None)
    save(d)


def use_invite(code: str, password: str) -> str:
    """Set the password with a valid invite; the invite is used up. Returns the member's name."""
    _check_strength(password)
    h = _h(code or "")
    for name, m in load()["members"].items():
        inv = m.get("invite")
        if inv and hmac.compare_digest(h, inv["sha256"]):
            if inv["expires"] < time.time():
                raise ValueError("this invite has expired: ask the coordinator for a new one")
            set_password(name, password)
            return name
    raise ValueError("this invite isn't valid (already used?): ask the coordinator for a new one")


def _locked(name: str) -> bool:
    recent = [t for t in _FAILS.get(name, []) if time.time() - t < 60]
    _FAILS[name] = recent
    return len(recent) >= 5


def verify(name: str, password: str) -> tuple[str, str] | None:
    """(name, role) when the password is right. Five wrong tries lock the name for a minute."""
    if _locked(name):
        raise PermissionError("too many wrong passwords: wait a minute and try again")
    m = load()["members"].get(name)
    pw = (m or {}).get("password")
    if pw:
        got = _hash_pw(password, bytes.fromhex(pw["salt"]))
        if hmac.compare_digest(got, pw["scrypt"]):
            _FAILS.pop(name, None)
            return name, m["role"]
    else:
        _hash_pw(password, b"0" * 16)          # same time whether or not the name exists
    _FAILS.setdefault(name, []).append(time.time())
    return None


# ---- sessions (the browser) ---------------------------------------------------------------------

def _sessions_path() -> Path:
    return _dir() / "sessions.json"


def _sessions() -> dict:
    p = _sessions_path()
    s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {k: v for k, v in s.items() if v["expires"] > time.time()}


def _save_sessions(s: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    _sessions_path().write_text(json.dumps(s, indent=1), encoding="utf-8")


def new_session(name: str) -> str:
    sid = secrets.token_urlsafe(32)
    s = _sessions()
    s[_h(sid)] = {"name": name, "expires": time.time() + SESSION_DAYS * 86400, "at": _now()}
    _save_sessions(s)
    return sid


def check_session(sid: str | None) -> tuple[str, str] | None:
    if not sid:
        return None
    rec = _sessions().get(_h(sid))
    m = load()["members"].get(rec["name"]) if rec else None
    return (rec["name"], m["role"]) if m else None


def end_session(sid: str | None) -> None:
    if sid:
        s = _sessions()
        s.pop(_h(sid), None)
        _save_sessions(s)


def end_sessions(name: str) -> None:
    _save_sessions({k: v for k, v in _sessions().items() if v["name"] != name})


# ---- listener tokens ----------------------------------------------------------------------------

def issue_token(name: str) -> str:
    """A new listener token for a member (replacing any old one); shown once, stored as a hash."""
    d = load()
    if name not in d["members"]:
        raise ValueError(f"no member {name!r}")
    token = "am_" + secrets.token_urlsafe(32)
    d["members"][name]["token_sha256"] = _h(token)
    save(d)
    return token


def check(token: str | None) -> tuple[str, str] | None:
    """(name, role) for a valid listener token, else None. Constant-time comparison."""
    if not token:
        return None
    h = _h(token)
    for name, m in load()["members"].items():
        if m.get("token_sha256") and hmac.compare_digest(h, m["token_sha256"]):
            return name, m["role"]
    return None


# ---- who is asking ------------------------------------------------------------------------------

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
