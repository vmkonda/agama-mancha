"""The shared catalog of every PDF in the team library (docs/plan.md, phase A).

The catalog only reflects the library listing, so refreshing is safe to repeat and two
people refreshing at once is harmless. What people do with a book (claims, stages,
progress) lives in that book's own status file, which a refresh never touches.

  local copy:  data/library/catalog.json  (+ changes.jsonl)
  shared copy: <material folder>/catalog/catalog.json  (+ changes.jsonl)

Entries are matched across refreshes by path; a PDF that disappears from one path and
appears at another with the same SHA-1 (or, without one, the same name and size) has
moved, and keeps its history.
"""

from __future__ import annotations

import json
import posixpath
from datetime import datetime, timezone
from pathlib import Path

from .catalog import data_dir

SKIP = ("[OCR Mirror]",)  # the team's OCR copies live inside the library tree too


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_dir() -> Path:
    return data_dir() / "library"


def local_path() -> Path:
    return local_dir() / "catalog.json"


def load() -> dict:
    p = local_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"entries": []}


def save(cat: dict) -> None:
    local_dir().mkdir(parents=True, exist_ok=True)
    tmp = local_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(local_path())


def age_hours(cat: dict) -> float | None:
    at = cat.get("refreshed_at")
    if not at:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() / 3600


# ---- reading the library (read-only, through the Proton wrapper) ---------------------

def _items(pd, path: str) -> list[dict]:
    # The wrapper's allow-listed read operation; every call is checked and logged there.
    out = pd._run("filesystem", "list", path, "--json").stdout
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def _name(it: dict) -> str | None:
    n = it.get("name")
    return n.get("value") if isinstance(n, dict) and n.get("ok") else (n if isinstance(n, str) else None)


def _seg(name: str) -> str:
    """A name as one path segment: the CLI wants a / inside a name escaped as \\/."""
    return name.replace("/", "\\/")


def split_path(path: str) -> list[str]:
    """A catalog path's segments, with escaped slashes restored."""
    import re

    return [p.replace("\\/", "/") for p in re.split(r"(?<!\\)/", path)]


def list_library(pd, root: str, unreadable: list[dict] | None = None) -> list[dict]:
    """Every PDF under root: {path (relative to root), name, folder, size, modified, sha1, added_by}.

    Paths are in the drive's form (a / inside a name escaped as \\/). A folder that can't
    be listed is skipped and its relative path added to `unreadable`."""
    from .proton import ProtonError

    out = []

    def walk(path: str, rel: str) -> None:
        try:
            items = _items(pd, path)
        except ProtonError as e:
            if not rel:
                raise
            if unreadable is not None:
                unreadable.append({"folder": rel, "error": str(e)})
            return
        for it in items:
            name = _name(it)
            if not name:
                continue
            seg = _seg(name)
            if it.get("type") == "folder":
                if name not in SKIP:
                    walk(f"{path}/{seg}", f"{rel}/{seg}" if rel else seg)
            elif name.lower().endswith(".pdf"):
                rev = it.get("activeRevision") or {}
                author = rev.get("contentAuthor") or {}
                out.append({
                    "path": f"{rel}/{seg}" if rel else seg,
                    "name": name,
                    "folder": split_path(rel)[0] if rel else "",
                    "size": rev.get("claimedSize") or it.get("totalStorageSize") or 0,
                    "modified": it.get("modificationTime") or "",
                    "sha1": (rev.get("claimedDigests") or {}).get("sha1"),
                    "added_by": author.get("value") if author.get("ok") else None,
                })

    walk(root.rstrip("/"), "")
    return out


# ---- merging a new listing into the catalog -------------------------------------------

def merge(old: list[dict], listing: list[dict], now: str | None = None,
          unread: list[str] = ()) -> tuple[list[dict], dict]:
    """New catalog entries and a summary of what changed. Pure: no I/O.

    Entries under an `unread` folder (one that couldn't be listed) keep their state."""
    now = now or _now()
    by_path = {e["path"]: e for e in old}
    seen, entries = set(), []
    changes = {"added": [], "gone": [], "moved": [], "changed": []}
    unmatched_new = []
    for item in listing:
        prev = by_path.get(item["path"])
        if prev and prev.get("state") != "gone":
            e = prev | {k: item[k] for k in ("name", "folder", "size", "modified", "sha1", "added_by")}
            if (prev.get("sha1") and item.get("sha1") and prev["sha1"] != item["sha1"]) or \
               (not (prev.get("sha1") and item.get("sha1")) and prev.get("size") != item.get("size")):
                e["state"] = "changed"
                changes["changed"].append(item["path"])
            elif e.get("state") in ("new", "changed", "moved"):
                e["state"] = "listed"
            e["last_seen"] = now
            entries.append(e)
            seen.add(item["path"])
        else:
            unmatched_new.append(item)
    # Old entries no longer at their path: moved (same file elsewhere) or gone.
    under = lambda p: any(p.startswith(u + "/") for u in unread)
    kept = [e for p, e in by_path.items() if p not in seen and e.get("state") != "gone" and under(p)]
    entries += kept
    seen |= {e["path"] for e in kept}
    missing = [e for p, e in by_path.items() if p not in seen and e.get("state") != "gone"]

    def same_file(a: dict, b: dict) -> bool:
        if a.get("sha1") and b.get("sha1"):
            return a["sha1"] == b["sha1"]
        return a.get("name") == b.get("name") and a.get("size") == b.get("size")

    for item in unmatched_new:
        twin = next((e for e in missing if same_file(e, item)), None)
        if twin:
            missing.remove(twin)
            e = twin | {k: item[k] for k in item} | {"state": "moved", "last_seen": now,
                                                     "moved_from": (twin.get("moved_from") or []) + [twin["path"]]}
            changes["moved"].append(f"{twin['path']} -> {item['path']}")
        else:
            e = item | {"state": "new", "first_seen": now, "last_seen": now}
            changes["added"].append(item["path"])
        entries.append(e)
    for e in missing:
        entries.append(e | {"state": "gone", "gone_since": now})
        changes["gone"].append(e["path"])
    entries += [e for e in old if e.get("state") == "gone" and e["path"] not in {x["path"] for x in entries}]
    entries.sort(key=lambda e: e["path"].lower())
    return entries, changes


# ---- refresh, and sharing through the material folder ---------------------------------

def remote_dir(cfg) -> str | None:
    from .proton import results_root

    if not (cfg.proton_root and cfg.material.strip()):
        return None
    return posixpath.join(results_root(cfg.proton_root, cfg.material), "catalog")


def refresh(operator: str = "", share: bool = True) -> dict:
    """List the library, merge, save locally, and share through the material folder when it exists.

    share=False reads only: no shared copy is pulled or uploaded."""
    from . import book
    from . import config as cfgmod

    pd, cfg = book._proton()
    old = (pull(pd, cfg) if share else None) or load()
    unreadable: list[dict] = []
    listing = list_library(pd, cfg.proton_root, unreadable)
    entries, changes = merge(old.get("entries", []), listing, unread=[u["folder"] for u in unreadable])
    cat = {"root": cfg.proton_root, "refreshed_at": _now(), "refreshed_by": operator or cfgmod.load().operator,
           "count": len([e for e in entries if e.get("state") != "gone"]), "entries": entries}
    save(cat)
    summary = {"at": cat["refreshed_at"], "by": cat["refreshed_by"], "pdfs": cat["count"],
               **{k: len(v) for k, v in changes.items()}, "unreadable": unreadable, "details": changes}
    with (local_dir() / "changes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    summary["shared"] = push(pd, cfg) if share else "not shared: --local"
    return summary


def push(pd, cfg) -> str:
    """Upload the catalog and change log to the material folder, if it exists."""
    rdir = remote_dir(cfg)
    if not rdir:
        return "not shared: no material folder set"
    from .proton import results_root

    if not pd.exists(results_root(cfg.proton_root, cfg.material)):
        return "not shared yet: the material folder doesn't exist on the drive"
    pd.mkdir_p(rdir)
    for f in ("catalog.json", "changes.jsonl"):
        if (local_dir() / f).exists():
            pd.upload(local_dir() / f, rdir)
    return f"shared to {rdir}"


def pull(pd, cfg) -> dict | None:
    """The shared catalog, if it is newer than the local one (and save it locally)."""
    rdir = remote_dir(cfg)
    if not rdir or not pd.exists(posixpath.join(rdir, "catalog.json")):
        return None
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(dir=data_dir()))
    try:
        pd.download(posixpath.join(rdir, "catalog.json"), tmp)
        remote = json.loads((tmp / "catalog.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    local = load()
    if remote.get("refreshed_at", "") > local.get("refreshed_at", ""):
        save(remote)
        return remote
    return local
