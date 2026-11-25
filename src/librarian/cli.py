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
    elif a.cmd == "mcp":
        from .mcp_server import main as run

        run()
