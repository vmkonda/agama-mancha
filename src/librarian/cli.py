"""librarian ingest | build | search | get | works | mcp"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="librarian", description="The Agama Mancha librarian: library, index, MCP tool.")
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
    p = sub.add_parser("study", help="the reader's study chat, from Claude's side: wait, reply, show")
    p.add_argument("action", choices=["wait", "reply", "show"])
    p.add_argument("msg", nargs="?", help="reply: the message id that `study wait` printed")
    p.add_argument("--text")
    p.add_argument("--cite", action="append", help="reply: a unit id the answer relies on (repeatable)")
    p.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args(argv)

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
    elif a.cmd == "study":
        from amocr import config as cfgmod

        from . import store, study

        if a.action == "wait":
            m = study.wait(a.timeout)
            if not m:
                print("no question yet (timed out); wait again")
                raise SystemExit(3)
            print(f"question {m['id']}{' about ' + m['unit'] if m.get('unit') else ''}:\n  {m['text']}\n")
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
