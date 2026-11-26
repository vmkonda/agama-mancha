"""librarian ingest | build | search | get | works | mcp"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="librarian", description="The Agama Mancha librarian: library, index, MCP tool.")
    ap.add_argument("--server", help="a hosted Agama Mancha (or AGAMA_SERVER): search, get and study go to it")
    ap.add_argument("--token", help="your member token for the hosted server (or AGAMA_TOKEN)")
    ap.add_argument("--hosted", action="store_true",
                    help="use the hosted server and token from ~/.config/agama-mancha/hosted.env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="GRETIL TEI files → library works (ET- ids) with units")
    p.add_argument("files", nargs="+")
    sub.add_parser("build", help="rebuild the search index from the library (a new build, swapped in when done)")
    p = sub.add_parser("search", help="hybrid search; prints passages")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=8)
    p.add_argument("--work")
    p.add_argument("--layer")
    p = sub.add_parser("get", help="one passage, with its commentary")
    p.add_argument("id")
    sub.add_parser("works", help="the works in the library")
    p = sub.add_parser("eval", help="run the evaluation questions against the current index")
    p.add_argument("--approved", action="store_true", help="only the questions the owner approved")
    sub.add_parser("mcp", help="run the MCP tool (stdio), for Claude Code")
    p = sub.add_parser("hosted", help="a hosted server: check that this machine can reach it with your token")
    p.add_argument("action", choices=["check"])
    p = sub.add_parser("gretil", help="GRETIL's catalogue: search it, or import a text into the library")
    p.add_argument("action", choices=["search", "import"])
    p.add_argument("what", help="search: words of the title; import: the TEI path (gretil/corpustei/sa_….xml)")
    p = sub.add_parser("study", help="the reader's study chat, from Claude's side: wait, reply, show")
    p.add_argument("action", choices=["wait", "reply", "show"])
    p.add_argument("msg", nargs="?", help="reply: the message id that `study wait` printed")
    p.add_argument("--text")
    p.add_argument("--cite", action="append", help="reply: a unit id the answer relies on (repeatable)")
    p.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args(argv)
    from . import remote

    srv = remote.server(a.server, hosted=a.hosted or a.cmd == "hosted")
    if a.cmd == "hosted":
        print(remote.check(srv, a.token))
        return
    if srv and a.cmd in ("search", "get", "study"):
        return _remote(a, srv)

    if a.cmd == "ingest":
        from . import etext

        for f in a.files:
            m = etext.ingest(Path(f))
            print(f"{m['id']}  {m['title']}: {m['units']} units, layers {', '.join(m['layers'])}")
    elif a.cmd == "build":
        from . import index

        print(json.dumps(index.build(), indent=1))
    elif a.cmd == "search":
        from . import index, store

        for h in index.search(a.query, k=a.k, work=a.work, layer=a.layer):
            u = store.get(h["id"], context=0)
            how = ", ".join(f"{x} #{h[x]}" for x in ("keyword", "meaning") if x in h)
            print(f"{u['id']}  [{u['title']}, {u['status']}; {how}]\n   {u['text'][:160]}\n   {(u.get('iast') or '')[:160]}")
    elif a.cmd == "get":
        from . import store

        print(json.dumps(store.get(a.id), ensure_ascii=False, indent=1))
    elif a.cmd == "works":
        from . import store

        for w in store.catalog():
            print(f"{w['id']:10} {w['units']:6}  {w['title']}  {w['author']}")
    elif a.cmd == "eval":
        from . import evals

        r = evals.run(only_approved=a.approved)
        print(f"{r['hits']}/{r['scored']} with a correct passage in the top {r['k']} (build {r['build']})")
        for t, v in r["by_type"].items():
            print(f"  {evals.TYPES.get(t, t)}: {v['hits']}/{v['n']}")
        for row in r["rows"]:
            if row["scored"] and not row["rank"]:
                print(f"  miss {row['id']}: top {', '.join(row['top'])}")
    elif a.cmd == "gretil":
        from . import gretil, importer

        if a.action == "search":
            for x in gretil.search(a.what):
                print(f"{x['path']}\n   {x['title']}")
        else:
            importer.from_gretil(a.what)
            import time

            while importer.JOB["state"] == "running":
                time.sleep(1)
            print("\n".join(importer.JOB["log"]))
            if importer.JOB["error"]:
                raise SystemExit(importer.JOB["error"])
    elif a.cmd == "study":
        from amocr import config as cfgmod

        from . import store, study

        if a.action == "wait":
            m = study.wait(a.timeout)
            if not m:
                print("no question yet (timed out); wait again")
                raise SystemExit(3)
            print(f"question {m['id']}{' about ' + m['unit'] if m.get('unit') else ''}:\n  {m['text']}\n")
            if m.get("quote"):
                print(f"the words they selected (the question is about these):\n  «{m['quote']}»\n")
            if m.get("unit"):
                u = store.get(m["unit"], context=2)
                if u:
                    print(f"the passage: {u['id']} ({u['title']}, {u['status']})\n  {u['text']}\n  {u.get('iast') or ''}")
                    for c in u.get("commentary", [])[:4]:
                        print(f"  commentary {c['id']}: {c['text'][:300]}")
                    print(f"  neighbours: {', '.join(u.get('neighbours', []))}")
            recent = [x for x in study.load() if x["id"] != m["id"]][-6:]
            if recent:
                print("\nearlier in this conversation:")
                for x in recent:
                    print(f"  {x['role']}: {x['text'][:200]}")
            print("\nAnswer only from the library: read what you need (librarian get/search, or the agama-librarian "
                  "tool), quote the original with a translation, and cite every passage you rely on:\n"
                  f"  uv run librarian study reply {m['id']} --text \"...\" --cite <unit id> [--cite ...]\nthen wait again.")
        elif a.action == "reply":
            if not (a.msg and a.text):
                raise SystemExit("reply needs the message id and --text")
            r = study.post("claude", a.text, reply_to=a.msg, cites=a.cite or [], by="claude")
            print(f"replied ({r['id']}) citing {len(r.get('cites', []))} passage(s)")
        else:
            for x in study.load()[-20:]:
                print(f"{x['at'][11:16]} {x['role']}{' [' + x['unit'] + ']' if x.get('unit') else ''}: {x['text'][:300]}")
    elif a.cmd == "mcp":
        from .mcp_server import main as run

        run()


def _remote(a, srv: str) -> None:
    """The same commands against a hosted server: every request goes out from this machine."""
    import time

    from . import remote

    if a.cmd == "search":
        q = {"q": a.query, "k": a.k, "work": a.work or "", "layer": a.layer or ""}
        for u in remote.call(srv, "/api/librarian/search", a.token, query=q):
            how = ", ".join(f"{x} #{v}" for x, v in (u.get("found_by") or {}).items())
            print(f"{u['id']}  [{u['title']}, {u['status']}; {how}]\n   {u['text'][:160]}\n   {(u.get('iast') or '')[:160]}")
    elif a.cmd == "get":
        print(json.dumps(remote.call(srv, "/api/librarian/unit", a.token, query={"id": a.id}), ensure_ascii=False, indent=1))
    elif a.action == "wait":
        end = time.time() + a.timeout
        while time.time() < end:
            r = remote.call_waiting(srv, "/api/librarian/study/next", a.token, query={"timeout": 25}, timeout=60)
            m = r.get("message")
            if not m:
                continue
            print(f"question {m['id']}{' about ' + m['unit'] if m.get('unit') else ''} (from {m.get('by', '?')} on {srv}):\n  {m['text']}\n")
            if m.get("quote"):
                print(f"the words they selected (the question is about these):\n  «{m['quote']}»\n")
            u = r.get("context")
            if u:
                print(f"the passage: {u['id']} ({u['title']}, {u['status']})\n  {u['text']}\n  {u.get('iast') or ''}")
                for c in u.get("commentary", [])[:4]:
                    print(f"  commentary {c['id']}: {c['text'][:300]}")
                print(f"  neighbours: {', '.join(u.get('neighbours', []))}")
            print("\nAnswer only from the library (librarian --server … get/search), quote the original with a translation, "
                  f"and cite every passage:\n  uv run librarian study reply {m['id']} --text \"...\" --cite <unit id> …\nthen wait again.")
            return
        print("no question yet (timed out); wait again")
        raise SystemExit(3)
    elif a.action == "reply":
        if not (a.msg and a.text):
            raise SystemExit("reply needs the message id and --text")
        r = remote.call(srv, "/api/librarian/study/reply", a.token, body={"reply_to": a.msg, "text": a.text, "cites": a.cite or []})
        print(f"replied ({r['id']}) to {srv}, citing {len(r.get('cites', []))} passage(s)")
    else:
        raise SystemExit("study show isn't available against a server; open the panel in the app")

