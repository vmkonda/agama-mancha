"""amocr: OCR for scanned Sanskrit/Hindi books, page by page, shared via Proton Drive.

Volunteer flow (or just ask Claude: "set me up")
  amocr doctor                               check tools, login and settings
  amocr setup-proton / setup-models          Proton CLI and pinned Tesseract models, no admin rights
  amocr folders                              what's shared with you on Proton
  amocr init --operator "Name" --proton-root "/shared-with-me/<team folder>"
  amocr fetch "/shared-with-me/<team folder>/<path>/book.pdf"   download + register + pull others' results
  amocr ocr <book> [--engine surya]          Tesseract (or local Surya) on every page (free, no Claude)
  amocr claude-next <book> -n 10             prepare the next 10 pages for Claude
  amocr claude-import <book> --ready         store every page Claude finished
  amocr push <book>                          upload results to the material folder on Proton Drive
  amocr status [<book>]                      progress
  amocr serve                                scan and text side by side in the browser

Also: add (local PDF), pull, inventory, render, eval, claude-prep, estimate, checksum.
<book> is the id shown by `amocr status` (e.g. B-1a2b3c4d5e), or SL-0001 for the pilot.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import config as cfgmod
from .catalog import Work, load_works, resolve, sha256_of, verify_source
from .engines import get_engine
from .metrics import cer
from .pages import inventory, native_dpi, read_jsonl, render, write_jsonl


def parse_pages(spec: str | None, n: int) -> list[int]:
    """'51', '51-60', '1,5,10-12', or None for all pages."""
    if not spec:
        return list(range(1, n + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    bad = [p for p in pages if not 1 <= p <= n]
    if bad:
        raise SystemExit(f"pages out of range 1-{n}: {bad[:5]}")
    return sorted(pages)


def _inventory(work: Work) -> list[dict]:
    path = work.workdir / "inventory.jsonl"
    if not path.exists():
        verify_source(work)
        write_jsonl(inventory(work.source), path)
    return read_jsonl(path)


def _needs_ocr(rows: list[dict]) -> list[int]:
    return [r["page"] for r in rows if r["text_layer"] in ("none", "suspect")]


def _image(work: Work, row: dict) -> Path:
    out = work.page_dir(row["page"]) / "image.png"
    if not out.exists():
        if not work.source.exists():
            verify_source(work)
        render(work.source, row["page"], out, native_dpi(row))
    return out


def _tesseract(work: Work, rows: list[dict], pages: list[int], langs="san+hin", psm=3, force=False, quiet=False) -> None:
    _run_engine(work, rows, pages, get_engine("tesseract", langs=langs, psm=psm), force, quiet)


def _run_engine(work: Work, rows: list[dict], pages: list[int], engine, force=False, quiet=False) -> None:
    try:
        _run_pages(work, rows, pages, engine, force, quiet)
    finally:
        engine.close()


def _run_pages(work: Work, rows: list[dict], pages: list[int], engine, force=False, quiet=False) -> None:
    operator = cfgmod.load().operator
    for p in pages:
        row = rows[p - 1]
        if row["text_layer"] not in ("none", "suspect") and not force:
            quiet or print(f"p{p}: usable text layer ({row['text_layer']}), skipped")
            continue
        out = work.page_dir(p) / "ocr" / f"{engine.label}-{engine.version()}.json"
        if out.exists() and not force:
            quiet or print(f"p{p}: already done ({out.name})")
            continue
        res = engine.run(_image(work, row))
        rec = res.to_json() | {
            "work": work.id, "page": p, "operator": operator, "amocr_version": __version__,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        out.with_suffix(".txt").write_text(res.text, encoding="utf-8")
        print(f"p{p}: {engine.name} conf {res.confidence}  {res.seconds}s")


# ---- per-book commands ------------------------------------------------------


def cmd_checksum(work: Work, args) -> None:
    print(sha256_of(work.source))


def cmd_inventory(work: Work, args) -> None:
    rows = _inventory(work)
    by_layer: dict[str, int] = {}
    for r in rows:
        by_layer[r["text_layer"]] = by_layer.get(r["text_layer"], 0) + 1
    dpis = sorted({native_dpi(r) for r in rows})
    print(f"{work.id}: {len(rows)} pages, text layer {by_layer}, scan dpi {dpis}")
    print(f"pages needing OCR: {len(_needs_ocr(rows))}")


def cmd_render(work: Work, args) -> None:
    rows = _inventory(work)
    for p in parse_pages(args.pages, len(rows)):
        print(_image(work, rows[p - 1]))


def cmd_ocr(work: Work, args) -> None:
    rows = _inventory(work)
    pages = parse_pages(args.pages, len(rows))
    if args.engine == "tesseract":
        _tesseract(work, rows, pages, args.langs, args.psm, args.force)
    elif args.engine == "surya":
        _run_engine(work, rows, pages, get_engine("surya"), args.force)
    else:
        raise SystemExit(f"unknown engine {args.engine!r} for `amocr ocr`: tesseract or surya (Claude runs via claude-next/claude-import)")


def cmd_eval(work: Work, args) -> None:
    gts = sorted(work.gt_dir.glob("p*.txt"))
    if not gts:
        raise SystemExit(f"no ground truth in {work.gt_dir} (files named p0051.txt etc.)")
    results: dict[str, list[tuple[int, float, float, float | None]]] = {}
    for gt in gts:
        page = int(gt.stem[1:])
        ref = gt.read_text(encoding="utf-8")
        for res in sorted((work.page_dir(page) / "ocr").glob("*.json")):
            rec = json.loads(res.read_text(encoding="utf-8"))
            results.setdefault(res.stem, []).append(
                (page, cer(rec["text"], ref), cer(rec["text"], ref, ignore_space=True), rec.get("confidence"))
            )
    for label, rs in sorted(results.items()):
        print(f"\n{label}")
        print(f"  {'page':>5} {'CER':>7} {'CER-nospace':>12} {'conf':>6}")
        for page, c, cn, conf in rs:
            print(f"  {page:>5} {c:>7.2%} {cn:>12.2%} {conf if conf is not None else '-':>6}")
        print(f"  {'mean':>5} {sum(r[1] for r in rs) / len(rs):>7.2%} {sum(r[2] for r in rs) / len(rs):>12.2%}")


def _no_claude_if_restricted(work: Work) -> None:
    if work.restricted:
        raise SystemExit(f"{work.id} is marked restricted: its pages must not be sent to Claude. Use Tesseract only.")


def _claude_mode(requested: str) -> str:
    """auto: review Surya's reading line by line when Surya is installed, else whole-page strips."""
    if requested != "auto":
        return requested
    try:
        import surya  # noqa: F401
        return "review"
    except ImportError:
        return "bands"


def _prep_pages(work: Work, rows: list[dict], pages: list[int], mode: str) -> list[tuple[int, Path]]:
    from .claude_review import base_result
    from .claude_session import prep

    for p in pages:
        _tesseract(work, rows, [p], quiet=True)
    if mode in ("review", "screen"):
        missing = [p for p in pages if not base_result(work, p)]
        if missing:
            print(f"Surya on {len(missing)} page(s) first ...")
            _run_engine(work, rows, missing, get_engine("surya"))
    return [(p, prep(work, p, _image(work, rows[p - 1]), mode)) for p in pages]


def _packet_help(mode: str) -> str:
    if mode == "screen":
        return ("Read screen.txt (text only) and write flags.json listing lines that may be misread "
                "(rules in CLAUDE.md); then `amocr claude-check` builds images of just those lines")
    if mode == "review":
        return "Read review.txt and the sheet*.png images, write result.json (mode \"review\", rules in CLAUDE.md)"
    return "Read band*.png and tesseract.txt, write result.json (rules in CLAUDE.md)"


def cmd_claude_prep(work: Work, args) -> None:
    _no_claude_if_restricted(work)
    rows = _inventory(work)
    mode = _claude_mode(args.mode)
    for p, d in _prep_pages(work, rows, parse_pages(args.pages, len(rows)), mode):
        print(f"p{p}: {d}")
    print(_packet_help(mode) + ".")


def cmd_claude_next(work: Work, args) -> None:
    from .claude_session import next_pages, ready

    _no_claude_if_restricted(work)
    waiting = ready(work)
    if waiting:
        print(f"{len(waiting)} finished page(s) not imported yet: run `amocr claude-import {work.id} --ready` first")
        return
    screening = [d.name for d in sorted((work.workdir / "claude").glob("p*")) if (d / "screen.txt").exists() and not (d / "result.json").exists()]
    if screening:
        print(f"{len(screening)} screened page(s) still need their image check ({', '.join(screening)}): "
              f"write flags.json, run `amocr claude-check {work.id}`, then result.json and `claude-import --ready`")
        return
    rows = _inventory(work)
    pages = next_pages(work, args.n, _needs_ocr(rows))
    if not pages:
        print(f"{work.id}: every page has a Claude result. Run `amocr push {work.id}`.")
        return
    mode = _claude_mode(args.mode)
    for p, d in _prep_pages(work, rows, pages, mode):
        print(f"p{p}: {d}")
    print(f"\n{len(pages)} page(s) ready for Claude ({mode} mode). {_packet_help(mode)} in each folder, "
          f"then `amocr claude-import {work.id} --ready`.")


def cmd_claude_check(work: Work, args) -> None:
    """Screen mode, step 2: line images for the lines flagged in flags.json (plus Tesseract disagreements)."""
    from .claude_review import prep_check
    from .claude_session import inbox

    _no_claude_if_restricted(work)
    rows = _inventory(work)
    done = 0
    for d in sorted((work.workdir / "claude").glob("p*")):
        page = int(d.name[1:])
        if not (d / "flags.json").exists() or (d / "result.json").exists():
            continue
        if (d / "check.txt").exists() and not args.force:
            continue
        n = len(json.loads((d / "lines.json").read_text(encoding="utf-8"))["lines"])
        by_claude, by_tess = prep_check(work, page, _image(work, rows[page - 1]), inbox(work, page))
        print(f"p{page}: check {len(by_claude) + len(by_tess)} of {n} lines "
              f"({len(by_claude)} flagged from the text, {len(by_tess)} where Tesseract disagrees)")
        done += 1
    if not done:
        print("no pages waiting for a check (they need flags.json and no result.json yet)")
        return
    print(f"\nRead check.txt and the check*.png images in each folder, write result.json (mode \"screen\"), "
          f"then `amocr claude-import {work.id} --ready`.")


def cmd_patterns(work: Work, args) -> None:
    """Rules learned from corrections, with how many places each would still change (text only)."""
    from . import patterns as pat

    data = pat.merge_mined(work, include_claude=args.include_claude) if args.mine else pat.load(work)
    n = pat.counts(work)
    rules = sorted(data["rules"], key=lambda r: (-n.get(r["id"], 0), -r["count"]))
    print(f"{work.id}: {len(rules)} rules, {sum(n.values())} pending suggestions, {len(data['decisions'])} decided")
    for r in rules:
        state = "on " if r["enabled"] else "off"
        note = f"  ({r['note']})" if r.get("note") else ""
        print(f"  {state} {r['id']} {r['kind']:8s} {r['from']} → {r['to']}   seen {r['count']}x, pending {n.get(r['id'], 0)}{note}")
    if args.examples:
        for r in rules[: args.examples]:
            for sgg in pat.suggest(work, r["id"], limit=3):
                print(f"      p{sgg['page']} line {sgg['n']}: {sgg['line']}")


def cmd_line(work: Work, args) -> None:
    """One line's image and current text, for Claude to look at when a proofreader asks."""
    from . import patterns as pat

    _no_claude_if_restricted(work)
    d = pat.draft(work, args.page)
    if not d:
        raise SystemExit(f"p{args.page}: no text yet")
    rows = [ln for ln in d["text"].split("\n") if ln.strip()]
    lines = range(args.line - 1, args.line + args.context) if args.context else [args.line - 1]
    out_dir = work.workdir / "claude" / "ask"
    out_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    _image(work, _inventory(work)[args.page - 1])
    with Image.open(work.page_dir(args.page) / "image.png") as im:
        for i in lines:
            if not 0 <= i < len(rows):
                continue
            box = d["boxes"][i] if i < len(d["boxes"]) else None
            print(f"p{args.page} line {i + 1} ({d['source']}): {rows[i]}")
            if box:
                path = out_dir / f"p{args.page:04d}-l{i + 1:02d}.png"
                im.crop((max(0, box[0] - 8), max(0, box[1] - 8), min(im.width, box[2] + 8), min(im.height, box[3] + 8))).save(path)
                print(f"  image: {path}")


def _chat_remote(args) -> None:
    """The proofreading chat on a hosted server: wait for your next question (in one book, or `any`),
    reply with proposed fixes. Every connection goes out from this machine."""
    import tempfile
    import time as _time

    from librarian import remote

    srv = remote.server(args.server, hosted=True)
    if not srv:
        raise SystemExit("which server? --server, or AGAMA_SERVER in ~/.config/agama-mancha/hosted.env")
    book = "" if args.work == "any" else args.work
    if args.action == "wait":
        end = _time.time() + args.timeout
        print(f"listening on {srv} for {'all your books' if not book else book} ...", flush=True)
        while _time.time() < end:
            r = remote.call_waiting(srv, "/api/chat/next", args.token, query={"work": book, "timeout": 25}, timeout=60)
            m = r.get("message")
            if not m:
                continue
            wid = r["work"]
            where = (f" (p{m['page']}" + (f" lines {m['n']}-{m['n2']}" if m.get("n2") else f" line {m['n']}" if m.get("n") else "") + ")") if m.get("page") else ""
            print(f"message {m['id']} in {wid}{where}" + (" CHECK REQUEST" if m.get("kind") == "check" else "") + f" (from {m.get('by', '?')}):")
            print(f"  {m['text']}")
            ctx = r.get("context") or {}
            for x in ctx.get("lines") or ([ctx] if ctx.get("text") else []):
                print(f"line {x.get('n', m.get('n'))} ({x.get('source')}{', verified' if x.get('verified') else ''}): {x.get('text')}")
            if ctx.get("error"):
                print(f"(no line context: {ctx['error']})")
            if ctx.get("image_url"):
                img = Path(tempfile.gettempdir()) / f"amocr-{wid}-{Path(ctx['image_url']).name}"
                img.write_bytes(remote.fetch(srv, ctx["image_url"], args.token))
                print(f"image of {'these lines' if m.get('kind') == 'check' else 'the line'}: {img}")
            if r.get("brief_url"):
                print(f"book brief: {srv}{r['brief_url']} (librarian-style: read it once per session with `curl` or ask)")
            if m.get("kind") == "check":
                print("Check each line against the image. Reply with what matches, and a --fix for every line that differs "
                      "(whole line, as printed; misprints stay). Put anything unsure in the text.")
            print(f"\nReply with `uv run amocr chat {wid} reply {m['id']} --hosted --text \"...\"`"
                  " [--fix PAGE:LINE:\"whole new line\"] [--rule RULE_ID], then wait again.")
            return
        print("no message before the timeout; wait again")
        sys.exit(3)
    if args.action == "reply":
        if not (args.msg and book):
            raise SystemExit("reply needs the book and the message id")
        fixes = []
        for f in args.fix or []:
            try:
                page, n, to = f.split(":", 2)
            except ValueError:
                raise SystemExit("--fix is PAGE:LINE:new text") from None
            fixes.append({"page": int(page), "n": int(n), "to": to})
        r = remote.call(srv, f"/api/{book}/chat/reply", args.token,
                        body={"msg": args.msg, "text": args.text or "", "fixes": fixes, "rules": args.rule or []})
        print(f"replied ({r['id']}) on {srv} with {len(r.get('actions') or [])} action(s); the proofreader applies them in the viewer")
        return
    raise SystemExit("chat show isn't available against a server; open the chat panel in the app")


def cmd_chat(work: Work, args) -> None:
    """The proofreader's chat panel, from Claude's side: wait for a message, reply, or show history."""
    from . import chat

    if args.action == "show":
        for m in chat.load(work)[-args.last:]:
            where = f" p{m['page']}" + (f" line {m['n']}" if m.get("n") else "") if m.get("page") else ""
            print(f"[{m['at'][11:16]}] {m['role']}{where}: {m['text']}")
            for a in m.get("actions", []):
                print(f"    action: {a}")
        return
    if args.action == "wait":
        _no_claude_if_restricted(work)
        from . import brief as briefmod

        print(f"listening for {work.id} (the viewer shows Claude as listening) ...", flush=True)
        if briefmod.brief_path(work).exists():
            print(f"book brief: {briefmod.brief_path(work)} (read it once in this session before checking lines)", flush=True)
        m = chat.wait(work, timeout=args.timeout)
        if not m:
            print("no message before the timeout. Run `amocr chat <book> wait` again to keep listening.")
            sys.exit(3)
        where = (f" (p{m['page']}" + (f" lines {m['n']}-{m['n2']}" if m.get("n2") else f" line {m['n']}" if m.get("n") else "") + ")") if m.get("page") else ""
        print(f"message {m['id']}{where}" + (" CHECK REQUEST" if m.get("kind") == "check" else "") + ":")
        print(f"  {m['text']}")
        if m.get("kind") == "check" and m.get("page") and m.get("n"):
            try:
                ctx = chat.range_context(work, m["page"], m["n"], m.get("n2") or m["n"])
                for x in ctx["lines"]:
                    print(f"line {x['n']} ({x['source']}{', verified' if x['verified'] else ''}): {x['text']}")
                if ctx.get("image"):
                    print(f"image of these lines: {ctx['image']}")
                print("Check each line against the image. Reply with what matches, and a --fix for every line that differs "
                      "(whole line, as printed; misprints stay). Put anything unsure in the text.")
            except ValueError as e:
                print(f"(no line context: {e})")
        elif m.get("page") and m.get("n"):
            try:
                ctx = chat.line_context(work, m["page"], m["n"])
                print(f"line {m['n']} as it stands ({ctx['source']}{', verified' if ctx['verified'] else ''}): {ctx['text']}")
                if ctx.get("image"):
                    print(f"line image: {ctx['image']}")
            except ValueError as e:
                print(f"(no line context: {e})")
        print(f"\nReply with `uv run amocr chat {work.id} reply {m['id']} --text \"...\"`"
              f" [--fix PAGE:LINE:\"whole new line\"] [--rule RULE_ID], then wait again.")
        return
    # reply
    if not args.msg:
        raise SystemExit("chat reply needs the message id")
    if not any(m["id"] == args.msg and m["role"] == "user" for m in chat.load(work)):
        raise SystemExit(f"no message {args.msg} from the proofreader")
    actions = []
    for f in args.fix or []:
        try:
            page, n, to = f.split(":", 2)
        except ValueError:
            raise SystemExit("--fix is PAGE:LINE:new text") from None
        actions.append(chat.check_action(work, {"type": "line", "page": page, "n": n, "to": to}))
    for rid in args.rule or []:
        actions.append(chat.check_action(work, {"type": "rule", "id": rid}))
    m = chat.post(work, "claude", args.text or "", reply_to=args.msg, actions=actions or None)
    print(f"replied ({m['id']}) with {len(actions)} action(s); the proofreader applies them in the viewer")


def cmd_profile(work: Work, args) -> None:
    """A book's typeface look-alikes and metre, used by `amocr suspects`."""
    from . import suspects as sus

    prof = dict((work.extra or {}).get("profile") or {})
    changed = False
    if args.clear_lookalikes:
        prof["lookalikes"], changed = [], True
    for frm, to, why in args.lookalike or []:
        prof.setdefault("lookalikes", []).append([frm, to, why])
        changed = True
    if args.metre is not None:
        prof["metre"], changed = (args.metre or None), True
    if changed:
        work.extra = (work.extra or {}) | {"profile": prof}
        work.save()
    full = sus.profile(work)
    print(f"{work.id}: metre {full['metre'] or 'not checked'}; {len(full['lookalikes'])} look-alike rules")
    for frm, to, why in full["lookalikes"]:
        print(f"  {frm} → {to}   ({why})")


def cmd_suspects(work: Work, args) -> None:
    """Score every line from the text alone and list the ones worth a second look."""
    from . import patterns as pat
    from . import suspects as sus

    if args.eval:
        r = sus.evaluate(work, args.min_score)
        print(f"{work.id}: scored the engine's reading of {len(r['pages'])} corrected pages ({r['lines']} lines)")
        print(f"  known corrections: {r['errors']}; flagged at score >= {args.min_score}: {r['flagged']} lines")
        print(f"  caught {len(r['caught'])} of {r['errors']}; flagged but not (yet) corrected: {r['false_flags']}")
        for (p, n), a, b in r["missed"]:
            print(f"  missed p{p} line {n}: {a}  →  {b}")
        return
    rows = _inventory(work)
    pages = parse_pages(args.pages, len(rows)) if args.pages else None
    scored = sus.score_book(work, pages)
    hits = [e for e in scored if e["score"] >= args.min_score]
    print(f"{work.id}: {len(hits)} of {len(scored)} lines score >= {args.min_score}")
    for e in sorted(hits, key=lambda e: (-e["score"], e["page"], e["n"]))[: args.limit]:
        print(f"  p{e['page']} line {e['n']} [{e['score']}] {e['text']}")
        for r in e["reasons"]:
            print(f"      {r}")
    if args.add_rules:
        added = set()
        for e in scored:
            for f in e["fixes"]:
                # Context findings (को before तरह) become context rules below, never whole-word rules.
                if f["why"] != "context" and (f["from"], f["to"]) not in added and f["seen"] >= 5 * max(1, f["rare"]):
                    pat.add_rule(work, "word", f["from"], f["to"], source="scorer",
                                 note=f"{f['why']}: '{f['to']}' {f['seen']}x in this book, '{f['from']}' {f['rare']}x")
                    added.add((f["from"], f["to"]))
        n_ctx = 0
        for r in sus.context_fixes(work):
            pat.add_rule(work, "regex", sus.context_regex(r), r["to"], source="scorer",
                         note=f"{r['from']} {r['next']} → {r['to']} {r['next']}: '{r['to']} {r['next']}' {r['seen']}x in this book, "
                              f"'{r['from']} {r['next']}' {r['count']}x ({r['why']})")
            n_ctx += 1
        print(f"added {len(added)} look-alike rules and {n_ctx} context rules to Suggestions")


def cmd_brief(work: Work, args) -> None:
    """The book's brief and glossary: show them, or collect sources for Claude to write them."""
    from . import brief

    if args.sources:
        rows = _inventory(work)
        print(brief.sources(work, parse_pages(args.pages, len(rows)) if args.pages else []))
        print(f"\nWrite the brief to {brief.brief_path(work)} and the glossary to {brief.glossary_path(work)} "
              '({"terms": [{"term": "...", "note": "..."}]}); see src/amocr/brief.py.')
        return
    p = brief.brief_path(work)
    print(p.read_text(encoding="utf-8") if p.exists() else f"No brief yet for {work.id}: run `amocr brief {work.id} --sources`.")
    print(f"\nglossary: {len(brief.glossary(work))} terms ({brief.glossary_path(work)})")


def cmd_assemble(work: Work, args) -> None:
    """Page texts -> units (work/chapter/verse/layer), saved as a new numbered build; --push shares it."""
    from . import assemble

    rows = _inventory(work)
    pages = parse_pages(args.pages, len(rows)) if args.pages else None
    at = {}
    for item in args.chapter_at or []:
        page, _, ch = item.partition("=")
        if not (page.isdigit() and ch.isdigit()):
            raise SystemExit(f"--chapter-at wants PAGE=CHAPTER, e.g. 121=7 (got {item!r})")
        at[int(page)] = int(ch)
    if at:
        work.extra.setdefault("chapter_at", {}).update({str(k): v for k, v in at.items()})
        if work.origin == "book":
            work.save()
    r = assemble.assemble(work, pages=pages, commentary_layer=args.commentary_layer, chapter_at=at)
    used = ", ".join(f"{n} {src}" for src, n in r["pages_used"].items())
    print(f"{r['work_id']}{' (provisional id)' if r['work_id_provisional'] else ''}: {r['units']} units "
          f"in {len(r['chapters'])} chapters from {used}")
    print(f"  {'new build' if r['new'] else 'unchanged, still'} {r['build']}: {r['path']}")
    if r["front_pages"]:
        print(f"  before chapter 1 (not assembled): pages {r['front_pages'][0]}-{r['front_pages'][-1]}")
    if r["skipped_after_colophon"]:
        print(f"  after a chapter's colophon (not assembled): {len(r['skipped_after_colophon'])} pages, "
              f"from {r['skipped_after_colophon'][0]}")
    gaps = {ch: v for ch, v in r["numbering"].items() if v["missing"] or v["twice"]}
    if gaps:
        print("  verse numbers to look at (a misread number, or a line taken for the wrong layer):")
        for ch, v in gaps.items():
            print(f"    chapter {ch}: missing {v['missing'] or '-'}, twice {v['twice'] or '-'}")
    if r["unnumbered_verse_lines"] or r["unmarked_commentary"]:
        print(f"  {r['unnumbered_verse_lines']} verse lines without a number, {r['unmarked_commentary']} commentary "
              "passages without a closing number (saved as 'unnumbered' / 'unmarked')")
    if args.push:
        cmd_push(work, args)


def cmd_reference(work: Work, args) -> None:
    """A reference e-text for the book's root text: add one, show it, or list the verse lines that differ."""
    from pathlib import Path

    from . import assemble, reference

    if args.action == "add":
        if not args.file:
            raise SystemExit("reference add needs the e-text file")
        m = reference.add(work, Path(args.file), args.name or Path(args.file).stem, url=args.url or "", licence=args.licence or "")
        print(f"{work.id}: reference '{m['name']}' with {m['segments']} half-verses in chapters "
              f"{m['chapters'][0]}-{m['chapters'][-1]} (kept in {reference.ref_dir(work)}, never in the repo)")
        return
    m = reference.info(work)
    if not m:
        raise SystemExit(f"{work.id} has no reference e-text; add one with `amocr reference {work.id} add <file> --name ...`")
    if args.action == "show":
        print(json.dumps(m, ensure_ascii=False, indent=1))
        return
    rows = _inventory(work)
    pages = parse_pages(args.pages, len(rows)) if args.pages else range(1, len(rows) + 1)
    total = differ = 0
    for p in pages:
        got = assemble.page_text(work, p)
        if not got:
            continue
        st = assemble.page_structure(work, p, "\n".join(ln["text"] for ln in got[0]))
        total += sum(1 for t in st["lines"] if t.get("ref"))
        for w_ in st["warnings"]:
            if w_.get("kind") == "reference":
                differ += 1
                print(f"p{p} line {w_['line']}: {w_['text']}")
    print(f"{differ} of {total} verse lines differ from {m['name']}")


def cmd_rule(work: Work, args) -> None:
    """Add a rule (Claude or a person generalising a fix), or switch one on or off."""
    from . import patterns as pat

    if args.action == "add":
        if not (args.frm and args.to is not None):
            raise SystemExit("rule add needs --from and --to")
        r = pat.add_rule(work, args.kind, args.frm, args.to, note=args.note or "", source=args.source)
        print(f"added {r['id']}: {r['kind']} {r['from']} → {r['to']}; {pat.counts(work).get(r['id'], 0)} places to review in Proofread")
    else:
        if not args.id:
            raise SystemExit(f"rule {args.action} needs a rule id (see `amocr patterns {work.id}`)")
        pat.set_enabled(work, args.id, args.action == "on")
        print(f"{args.id} {args.action}")


def cmd_claude_import(work: Work, args) -> None:
    from .claude_session import import_result, ready

    rows = _inventory(work)
    if args.ready:
        pages = ready(work)
        if not pages:
            print("nothing to import")
            return
    elif args.pages:
        pages = parse_pages(args.pages, len(rows))
    else:
        raise SystemExit("give --pages or --ready")
    operator = cfgmod.load().operator
    for p in pages:
        out, warnings = import_result(work, p, force=args.force, operator=operator)
        print(f"p{p}: stored {out.name}")
        for w in warnings:
            print(f"  WARNING: {w}")


def cmd_estimate(work: Work, args) -> None:
    """Dry run for a paid engine: pages x price, refuse above the cap."""
    rows = _inventory(work)
    pages = set(parse_pages(args.pages, len(rows)))
    todo = [p for p in _needs_ocr(rows) if p in pages]
    cost = len(todo) * args.price_per_page
    print(f"{len(todo)} pages x ${args.price_per_page:.4f} = ${cost:.2f} (cap ${args.cap:.2f})")
    if cost > args.cap:
        print("REFUSED: above cap")
        sys.exit(2)
    print("within cap")


def cmd_pull(work: Work, args) -> None:
    from .book import pull

    print(f"{work.id}: {pull(work)}")


def cmd_push(work: Work, args) -> None:
    from .book import push

    remote = push(work)
    print(f"{work.id}: uploaded to {remote}")
    _board_quietly()


def _inventory_quietly(w: Work) -> None:
    """Record a fetched book's text-layer facts and share them; never fail the fetch over it."""
    from . import board, book, inventory

    try:
        pd, cfg = book._proton()
        mine = inventory.load_mine(cfg.operator)
        f = inventory.record(mine, board.sha1_of(w), w.source)
        print(f"   {inventory.VERDICTS[f['verdict']]}" + (f", {f['script']}" if f.get("script") else ""))
        inventory.publish(pd, cfg, mine)
    except (SystemExit, Exception) as e:  # noqa: BLE001
        print(f"inventory not shared: {e}")


def cmd_sync(args) -> None:
    """On a server: bring the books in step with the material folder on Proton (pull, then push
    what changed). Meant to run on a schedule (scripts/windows/auto-sync.cmd, or cron)."""
    from . import sync

    try:
        failed = sync.sync(args.books or None, push_unchanged=args.push_all)
    except sync.Locked as e:
        raise SystemExit(str(e)) from None
    if failed:
        raise SystemExit(f"{failed} book(s) failed; see above (and data/sync.log)")


def _board_quietly() -> None:
    """Share this person's progress on the board; never fail the command over it."""
    from . import board

    try:
        board.refresh_board()
    except (SystemExit, Exception) as e:  # noqa: BLE001 - the board is a courtesy here
        print(f"board not updated: {e}")


# ---- commands that don't take a single book ---------------------------------


def cmd_duplicates(args) -> None:
    """Books on this machine twice (same PDF under two ids)."""
    from . import dedupe

    groups = dedupe.duplicates()
    if not groups:
        print("no duplicate books on this machine")
    for g in groups:
        print(f"same PDF ({g[0].sha256[:12]}…):")
        for w in g:
            print(f"   {w.id:14} {dedupe._pages(w):4} pages with output   {w.title}")
        print(f"   merge with: amocr merge {g[-1].id} {g[0].id} --dry-run")


def cmd_merge(args) -> None:
    """Merge a duplicate book into the one to keep; copies what's missing, never overwrites."""
    from . import dedupe

    works = load_works()
    for wid in (args.dup, args.keep):
        if wid not in works:
            raise SystemExit(f"unknown book {wid!r}; known: {', '.join(works)}")
    r = dedupe.merge(works[args.dup], works[args.keep], dry_run=args.dry_run)
    print(f"{args.dup} -> {args.keep}: {len(r['copy'])} files to copy, {r['same']} the same, "
          f"{len(r['kept'])} where {args.keep}'s machine output is kept, {len(r['conflicts'])} conflicts")
    for rel in r["copy"][:args.show]:
        print(f"   copy  {rel}")
    if len(r["copy"]) > args.show:
        print(f"   … and {len(r['copy']) - args.show} more")
    for rel in r["kept"]:
        print(f"   keep {args.keep}'s  {rel}  (the other goes to trash)")
    for rel in r["conflicts"]:
        print(f"   DIFFERS  {rel}")
    if r["conflicts"]:
        raise SystemExit("nothing changed: these files differ between the two books. Keep the right version in "
                         f"{args.keep}, delete the other from {args.dup}, then merge again.")
    if r["done"]:
        print(f"merged; {args.dup} moved to {r['trash']} (delete that folder when you're sure). "
              f"'{args.dup}' now means {args.keep}.")
    else:
        print("dry run: nothing changed. Run again without --dry-run to merge.")


def cmd_status(args) -> None:
    from .book import page_status

    works = load_works()
    ids = [resolve(works, args.work)] if args.work else list(works)
    for wid in ids:
        if wid not in works:
            raise SystemExit(f"unknown book {wid!r}")
        w = works[wid]
        if not (w.workdir / "inventory.jsonl").exists():
            print(f"{w.id}  {w.title}  (not started)")
            continue
        st = page_status(w)
        any_ = sum(1 for s in st.values() if s["results"])
        cl = sum(1 for s in st.values() if any(r["label"].startswith("claude") for r in s["results"]))
        gt = sum(1 for s in st.values() if s["groundtruth"])
        flags = " RESTRICTED" if w.restricted else ""
        print(f"{w.id}  {w.title}{flags}\n   {len(st)} pages · OCR {any_} · Claude {cl} · ground truth {gt}"
              + (f"\n   {w.remote}" if w.remote else ""))


def cmd_add(args) -> None:
    from .book import add

    pdf = Path(args.pdf).expanduser()
    if not pdf.is_file():
        raise SystemExit(f"no such file: {pdf}")
    w = add(pdf, title=args.title, restricted=args.restricted)
    print(f"added {w.id}  {w.title}")


def cmd_fetch(args) -> None:
    from .book import fetch

    w, pulled = fetch(args.remote, title=args.title, restricted=args.restricted)
    print(f"{w.id}  {w.title}\n   results from others: {pulled}")
    _inventory_quietly(w)
    print(f"next: `amocr ocr {w.id}` (Tesseract, all pages), then `amocr claude-next {w.id}`")


def cmd_init(args) -> None:
    cfg = cfgmod.load()
    for k in ("operator", "proton_root", "proton_bin", "material"):
        v = getattr(args, k)
        if v is not None:
            setattr(cfg, k, v.rstrip("/") if k == "proton_root" else v)
    cfgmod.save(cfg)
    print(f"saved {cfgmod.path()}")
    for k, v in vars(cfg).items():
        print(f"  {k} = {v!r}")


def cmd_doctor(args) -> None:
    from .proton import TESTED_VERSION, Proton, ProtonError

    ok = True

    def line(good: bool, what: str, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"  {'ok ' if good else 'NO '} {what}" + (f"\n       -> {hint}" if hint and not good else ""))

    cfg = cfgmod.load()
    print(f"amocr {__version__}, Python {sys.version.split()[0]}")
    from .setup import MODELS_LABEL, models_present

    tess = shutil.which("tesseract")
    line(bool(tess), "tesseract installed", "macOS: brew install tesseract · Windows: winget install UB-Mannheim.TesseractOCR "
         "· Linux: apt install tesseract-ocr")
    if models_present(["san", "hin"]):
        line(True, f"Sanskrit and Hindi models: pinned set {MODELS_LABEL}")
    elif tess:
        langs = set(subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace").stdout.split())
        line({"san", "hin"} <= langs, "Sanskrit and Hindi models", "uv run amocr setup-models")
        print("       note: `uv run amocr setup-models` gives every volunteer identical, pinned models")
    line(bool(cfg.operator), f"your name for credits: {cfg.operator!r}", 'amocr init --operator "Your Name"')
    line(bool(cfg.proton_root), f"team folder: {cfg.proton_root!r}", 'amocr init --proton-root "/shared-with-me/<team folder>"')
    try:
        pd = Proton(cfg.proton_bin)
        v = pd.version()
        line(True, f"Proton Drive CLI: {v.splitlines()[0] if v else '?'}")
        if TESTED_VERSION not in v:
            print(f"       note: amocr was tested with CLI {TESTED_VERSION}")
        if cfg.proton_root:
            from .proton import results_root

            line(pd.exists(cfg.proton_root), "team folder reachable (logged in, shared with you)",
                 "run `proton-drive auth login`, and ask for the folder to be shared with your Proton account")
            if not cfg.material.strip():
                line(False, "material folder set", 'run `amocr init --material "/shared-with-me/<material folder>"`')
            else:
                rr = results_root(cfg.proton_root, cfg.material)
                line(pd.exists(rr), f"material folder exists: {rr}", "ask the coordinator to create/share it; amocr never creates it")
    except ProtonError as e:
        line(False, "Proton Drive CLI", str(e))
    claude = shutil.which("claude")
    line(bool(claude), "Claude Code installed (only needed for the Claude step)", "https://claude.com/claude-code")
    print("all good" if ok else "fix the NO lines above")
    sys.exit(0 if ok else 1)


def cmd_setup_proton(args) -> None:
    from .setup import get_proton_cli

    path, sha = get_proton_cli()
    cfg = cfgmod.load()
    cfg.proton_bin = str(path)
    cfgmod.save(cfg)
    print(f"installed {path}\n  sha256 {sha}\n  saved as proton_bin in {cfgmod.path()}")
    print(f"next: sign in with  \"{path}\" auth login  (opens a browser, or prints a link to open on any device)")


def cmd_setup_models(args) -> None:
    from .setup import MODELS_LABEL, get_models, tessdata_dir

    got = get_models()
    print(f"Tesseract models ({MODELS_LABEL}) in {tessdata_dir()}: " + (f"downloaded {', '.join(got)}" if got else "already up to date"))


def cmd_folders(args) -> None:
    from .proton import Proton, ProtonError

    cfg = cfgmod.load()
    try:
        names = Proton(cfg.proton_bin).list(args.path)
    except ProtonError as e:
        raise SystemExit(f"{e}\n(signed in? run the Proton CLI with `auth login`)") from None
    print(f"{args.path}:")
    for n in names:
        print(f"  {n}")
    if not names:
        print("  (empty: ask the coordinator to share the library and the material folder with your Proton account)")


def cmd_catalog(args) -> None:
    """The shared catalog of every PDF in the library (docs/plan.md, phase A)."""
    from . import library

    if args.action == "refresh":
        cat = library.load()
        age = library.age_hours(cat)
        if args.if_older is not None and age is not None and age < args.if_older:
            print(f"catalog is {age:.1f} h old; not refreshing")
            return
        s = library.refresh(share=not args.local)
        print(f"{s['pdfs']} PDFs: +{s['added']} new, {s['moved']} moved, {s['changed']} changed, {s['gone']} gone ({s['shared']})")
        for u in s["unreadable"]:
            print(f"  couldn't list {u['folder']}: {u['error']} (its books keep their last state)")
        return
    if args.action == "inventory":
        from . import inventory

        if args.quality:
            r = inventory.run_quality(limit=args.limit, share=not args.local, redo=args.redo)
            print(", ".join(f"{v} {k}" for k, v in r.items() if k not in ("todo", "engine", "shared"))
                  + f" of {r['todo']} (read with {r['engine']}; {r['shared']})")
            return
        r = inventory.run(limit=args.limit, folder=args.folder, max_mb=args.max_mb, share=not args.local, redo=args.redo)
        print(f"checked {r['done']} of {r['todo']} PDFs in {r['minutes']} min, {r['failed']} failed ({r['shared']})")
        return
    from . import inventory

    cat = library.load()
    print(f"{cat.get('count', 0)} PDFs, refreshed {cat.get('refreshed_at', 'never')} by {cat.get('refreshed_by', '-')}")
    st = inventory.stats(cat, inventory.merged())
    names = inventory.VERDICTS | {"garbled": "text layer garbled", "layer-poor": "OCR layer poor", "layer-fair": "OCR layer fair",
                                  "layer-unchecked": "OCR layer not checked (--quality)"}
    print("   " + ", ".join(f"{st.get(k, 0)} {names.get(k, k)}" for k in ("ocr", "garbled", "layer-poor", "layer-fair", "layer-unchecked", "mixed", "text", "notpdf", "unknown", "error")
                         if st.get(k)) + "  (unknown: run `amocr catalog inventory`)")


def cmd_board(args) -> None:
    """Who is working on what, and how far each book has got."""
    from . import board, library

    if args.action in ("claim", "release") and not args.book:
        raise SystemExit(f"which book? amocr board {args.action} <book id, path or part of the title>")
    if args.action == "claim":
        r = board.claim(args.book)
        print(("claimed: " if r["ok"] else "not claimed: ") + r["entry"]["path"])
        print(f"   {r.get('shared', '')}" if r["ok"] else f"   {r['why']}")
        if r["ok"] and not any(w.remote and w.remote.endswith("/" + r["entry"]["path"]) for w in load_works().values()):
            root = library.load().get("root", "")
            print(f'next: amocr fetch "{root}/{r["entry"]["path"]}"')
        return
    if args.action == "release":
        r = board.release(args.book, args.why or "")
        print(("released: " if r["ok"] else "not released: ") + r["entry"]["path"])
        print(f"   {r.get('shared', '')}" if r["ok"] else f"   {r['why']}")
        return
    b = board.refresh_board() if args.action == "sync" else board.merge(board.load_all())
    rows = sorted(b.values(), key=lambda e: (e.get("holder") is None, e.get("path") or ""))
    if not rows:
        print("nobody has claimed or reported a book yet" + ("" if args.action == "sync" else " (amocr board sync)"))
    for e in rows:
        p = e.get("progress") or {}
        who = f"{e['holder']} since {e['since'][:10]}" + (" (stale)" if e.get("stale") else "") if e.get("holder") else "nobody"
        prog = f" · {p.get('read', 0)}/{p.get('pages', 0)} read, {p.get('proofread', 0)} saved, {p.get('checked', 0)} proofread, {p.get('validated', 0)} validated" if p.get("pages") else ""
        print(f"{e.get('title') or e.get('path')}\n   {board.STAGE_LABEL[e['stage']]}{prog} · {who}")


def cmd_start(args) -> None:
    """Refresh the catalog if it is more than a day old, then open the viewer."""
    from . import library

    age = library.age_hours(library.load())
    if age is None or age > 24:
        try:
            s = library.refresh()
            print(f"catalog: {s['pdfs']} PDFs, +{s['added']} new ({s['shared']})")
        except SystemExit as e:
            print(f"catalog not refreshed: {e}")
    _board_quietly()
    cmd_serve(args)


def cmd_serve(args) -> None:
    from .server import serve

    serve(port=args.port, open_browser=not args.no_browser, page=args.open, host=args.host, hosted=args.hosted)


def cmd_worker(args) -> None:
    """An OCR worker: lease pages from a hosted server's queue and read them with the engines here."""
    from librarian import remote

    from .worker import run

    srv = remote.server(args.server, hosted=True)
    if not srv:
        raise SystemExit("which server? --server, or AGAMA_SERVER in ~/.config/agama-mancha/hosted.env")
    run(srv, args.token, [e.strip() for e in args.engines.split(",")] if args.engines else None, args.batch, args.once)


def cmd_fix_worker(args) -> None:
    """The local AI that makes proofreaders' instructed fixes, for a hosted server or this machine's viewer."""
    from librarian import remote

    from . import fixer

    srv = f"http://127.0.0.1:{args.port}" if args.local else remote.server(args.server, hosted=True)
    if not srv:
        raise SystemExit("which server? --server, --local, or AGAMA_SERVER in ~/.config/agama-mancha/hosted.env")
    # A local viewer has no members: any token will do (and the hosted one stays out of local requests).
    fixer.run(srv, (args.token or "local") if args.local else args.token, args.model or fixer.MODEL, args.once,
              log=lambda m: print(m, flush=True))


def cmd_queue(args) -> None:
    """On the server: queue a book's pages for an engine, or show the queue."""
    from . import ocrqueue

    if args.book:
        works = load_works()
        wid = resolve(works, args.book)
        if wid not in works:
            raise SystemExit(f"unknown book {args.book!r}")
        rows = _inventory(works[wid])
        pages = parse_pages(args.pages, len(rows)) if args.pages else None
        print(f"{wid}: {ocrqueue.add(works[wid], args.engine, pages)} page(s) queued for {args.engine}")
    st = ocrqueue.status()
    for b, c in sorted(st["books"].items()):
        print(f"  {b}: {c['queued']} waiting, {c['leased']} being read, {c['done']} done, {c['failed']} set aside")
    for w, x in st["workers"].items():
        print(f"  worker {w} on {x['host']} ({', '.join(x['engines'])}), seen {x['seconds_ago']}s ago")


def cmd_member(args) -> None:
    """Members of a hosted server: add (an invite link to choose a password), invite (a new link, for a
    forgotten password), token (a listener token for their machine), list, remove."""
    from . import members

    link = lambda code: f"http://HOST:{args.port}/invite?code={code}"
    if args.action in ("add", "invite", "token", "remove") and not args.name:
        raise SystemExit(f'member {args.action} needs a name, e.g. amocr member {args.action} "Anna"')
    if args.action == "add":
        code = members.add(args.name, args.role)
        print(f"{args.name} ({args.role}) added. Send them this invite link (replace HOST with the server's address);")
        print(f"it works once, for {members.INVITE_DAYS} days, to choose their password:\n  {link(code)}")
    elif args.action == "invite":
        print(f"A new invite link for {args.name} (to set a new password; works once, {members.INVITE_DAYS} days):\n  {link(members.invite(args.name))}")
    elif args.action == "token":
        print(f"A new listener token for {args.name} (the old one stops working). Shown only now; it goes in")
        print(f"~/.config/agama-mancha/hosted.env on their machine, nowhere else:\n  {members.issue_token(args.name)}")
    elif args.action == "remove":
        print("removed (and signed out)" if members.remove(args.name) else f"no member {args.name!r}")
    else:
        for name, m in sorted(members.load()["members"].items()):
            state = "password set" if m.get("password") else "invited" if m.get("invite") else "no password yet"
            print(f"  {name:24} {m['role']:12} {state:16} {'listener token' if m.get('token_sha256') else ''}")

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="amocr", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def book_cmd(name, fn, pages=False, help=None):
        p = sub.add_parser(name, help=help)
        p.add_argument("work", metavar="book")
        if pages:
            p.add_argument("--pages", help="e.g. 51, 51-60, 1,5,10-12 (1-based PDF pages); default all")
        p.set_defaults(fn=fn, per_book=True)
        return p

    def plain_cmd(name, fn, help=None):
        p = sub.add_parser(name, help=help)
        p.set_defaults(fn=fn, per_book=False)
        return p

    p = plain_cmd("doctor", cmd_doctor, "check tools, Proton login and settings")
    plain_cmd("setup-proton", cmd_setup_proton, "download the Proton Drive CLI for this machine into data/bin")
    plain_cmd("setup-models", cmd_setup_models, "download pinned Sanskrit/Hindi Tesseract models into data/tessdata")
    p = plain_cmd("folders", cmd_folders, "list Proton folders shared with you (read-only)")
    p.add_argument("path", nargs="?", default="/shared-with-me")
    p = plain_cmd("init", cmd_init, "save your name and the team folder")
    p.add_argument("--operator", help="your name, credited on every page you process")
    p.add_argument("--proton-root", dest="proton_root", help='team folder, e.g. "/shared-with-me/Library"')
    p.add_argument("--proton-bin", dest="proton_bin", help="path to the proton-drive program")
    p.add_argument("--material", "--mirror", dest="material",
                   help='the material folder, where results go: a full path like "/shared-with-me/[OCR Mirror]/Agama Mancha", '
                        "or a folder name inside the team folder (--mirror is the old name)")
    p = plain_cmd("fetch", cmd_fetch, "download a PDF from Proton Drive and register it")
    p.add_argument("remote", help='Proton path, e.g. "/shared-with-me/Team/Tantra/book.pdf"')
    p.add_argument("--title")
    p.add_argument("--restricted", action="store_true", help="never send this book to Claude")
    p = plain_cmd("add", cmd_add, "register a local PDF (no Proton Drive)")
    p.add_argument("pdf")
    p.add_argument("--title")
    p.add_argument("--restricted", action="store_true")
    p = plain_cmd("status", cmd_status, "progress per book")
    p.add_argument("work", nargs="?", metavar="book")
    p = plain_cmd("catalog", cmd_catalog, "the shared catalog of every PDF in the library")
    p.add_argument("action", choices=["refresh", "show", "inventory"])
    p.add_argument("--if-older", type=float, help="refresh only if older than this many hours")
    p.add_argument("--local", action="store_true", help="read the library only; don't pull or share the catalog")
    p.add_argument("--limit", type=int, help="inventory: at most this many PDFs (smallest first)")
    p.add_argument("--folder", help="inventory: only this top-level folder, e.g. Texts")
    p.add_argument("--max-mb", dest="max_mb", type=float, help="inventory: skip PDFs larger than this")
    p.add_argument("--redo", action="store_true", help="inventory: measure again PDFs already measured")
    p.add_argument("--quality", action="store_true",
                   help="inventory: grade existing OCR layers by reading 3 pages afresh (Surya if installed)")
    p = plain_cmd("board", cmd_board, "who is working on which book, and how far each has got")
    p.add_argument("action", nargs="?", default="show", choices=["show", "sync", "claim", "release"])
    p.add_argument("book", nargs="?", help="for claim/release: a book id, catalog path, or a unique part of the title")
    p.add_argument("--why", help="for release: why (recorded)")
    p = plain_cmd("start", cmd_start, "refresh the catalog if stale, then open the viewer")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--open", help="start at a page")
    p = plain_cmd("serve", cmd_serve, "side-by-side viewer at http://127.0.0.1:8791")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--host", default="127.0.0.1", help="address to listen on; anything beyond this machine needs --hosted")
    p.add_argument("--hosted", action="store_true", help="members only: every request needs a member's token")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--open", help="start at a page, e.g. B-1a2b3c4d5e/231")

    p = book_cmd("ocr", cmd_ocr, pages=True, help="OCR pages with Tesseract or Surya (default: all pages)")
    p.add_argument("--engine", default="tesseract", choices=["tesseract", "surya"],
                   help="surya: local Surya 2.5 model (optional install, see docs/engines.md)")
    p.add_argument("--langs", default="san+hin")
    p.add_argument("--psm", type=int, default=3)
    p.add_argument("--force", action="store_true", help="redo pages that already have a result")
    mode_help = ("review: Claude checks every line of Surya's reading against line images; screen: Claude reads "
                 "Surya's text first and sees images only of lines it flags (fewest tokens); bands: whole-page strips; "
                 "auto: review if Surya is installed")
    p = book_cmd("claude-next", cmd_claude_next, help="prepare the next pages for Claude")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--mode", choices=["auto", "review", "screen", "bands"], default="auto", help=mode_help)
    p = book_cmd("patterns", cmd_patterns, help="rules learned from corrections, with pending suggestions")
    p.add_argument("--mine", action="store_true", help="learn from the corrected pages first")
    p.add_argument("--include-claude", action="store_true", help="also learn from Claude's review results")
    p.add_argument("--examples", type=int, default=0, help="show up to 3 example lines for the first N rules")
    p = book_cmd("line", cmd_line, help="one line's image and text (line numbers count non-blank lines)")
    p.add_argument("page", type=int)
    p.add_argument("line", type=int)
    p.add_argument("--context", type=int, default=0, help="also the next N lines")
    p = book_cmd("chat", cmd_chat, help="the viewer's chat panel, from Claude's side: wait, reply, show")
    p.add_argument("action", choices=["wait", "reply", "show"])
    p.add_argument("msg", nargs="?", help="reply: the message id that `chat wait` printed")
    p.add_argument("--text")
    p.add_argument("--fix", action="append", help='reply: propose a line, PAGE:LINE:"whole new line" (repeatable)')
    p.add_argument("--rule", action="append", help="reply: point to a rule whose fixes show in Proofread (repeatable)")
    p.add_argument("--timeout", type=float, default=1800, help="wait: seconds before giving up (default 30 min)")
    p.add_argument("--last", type=int, default=20, help="show: how many messages")
    p.add_argument("--hosted", action="store_true", help="the hosted server in ~/.config/agama-mancha/hosted.env "
                   "(book may then be `any`: all your books)")
    p.add_argument("--server", help="a hosted server's address (instead of the file)")
    p.add_argument("--token", help="your listener token (instead of the file)")
    p = book_cmd("profile", cmd_profile, help="a book's typeface look-alikes and metre (for `suspects`)")
    p.add_argument("--lookalike", nargs=3, action="append", metavar=("FROM", "TO", "WHY"),
                   help='e.g. --lookalike ो ी "ी printed like ो"; ^भा = at word start; +र् = a dropped reph')
    p.add_argument("--clear-lookalikes", action="store_true")
    p.add_argument("--metre", type=int, help="syllables per verse line (16 for anuṣṭubh half-verses); 0 = don't check")
    p = book_cmd("suspects", cmd_suspects, pages=True, help="lines worth a second look, scored from the text alone")
    p.add_argument("--min-score", type=int, default=2)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--eval", action="store_true", help="measure against the lines already corrected")
    p.add_argument("--add-rules", action="store_true", help="send confident look-alike fixes to Suggestions")
    p = book_cmd("brief", cmd_brief, pages=True, help="the book's brief and glossary (or --sources to write them)")
    p.add_argument("--sources", action="store_true", help="collect structure, frequent words and the given pages' text")
    p = book_cmd("assemble", cmd_assemble, pages=True,
                 help="page texts -> units (work/chapter/verse/layer) as a numbered build (Phase D)")
    p.add_argument("--commentary-layer", help="name of the commentary layer, e.g. hindi-mishra (remembered)")
    p.add_argument("--chapter-at", action="append", metavar="PAGE=CHAPTER",
                   help="where a chapter starts when its heading isn't recognised (repeatable, remembered)")
    p.add_argument("--push", action="store_true", help="then upload the book's folder, builds included")
    p = book_cmd("reference", cmd_reference, pages=True,
                 help="a reference e-text of the root text (e.g. GRETIL): add, show, or check verse lines against it")
    p.add_argument("action", choices=["add", "show", "check"])
    p.add_argument("file", nargs="?", help="add: the e-text file (GRETIL plain text)")
    p.add_argument("--name", help="add: a short name shown in warnings, e.g. GRETIL")
    p.add_argument("--url")
    p.add_argument("--licence")
    p = book_cmd("rule", cmd_rule, help="add a rule, or switch one on/off")
    p.add_argument("action", choices=["add", "on", "off"])
    p.add_argument("id", nargs="?")
    p.add_argument("--kind", choices=["word", "fragment", "regex"], default="regex")
    p.add_argument("--from", dest="frm")
    p.add_argument("--to")
    p.add_argument("--note")
    p.add_argument("--source", default="claude", help="who wrote it: claude or a person's name")
    p = book_cmd("claude-check", cmd_claude_check, help="screen mode: build images of the flagged lines")
    p.add_argument("--force", action="store_true", help="rebuild check packets that already exist")
    p = book_cmd("claude-import", cmd_claude_import, pages=True, help="store Claude's finished pages")
    p.add_argument("--ready", action="store_true", help="every page with a result.json not yet imported")
    p.add_argument("--force", action="store_true")
    p = book_cmd("claude-prep", cmd_claude_prep, pages=True, help="prepare specific pages for Claude")
    p.add_argument("--mode", choices=["auto", "review", "screen", "bands"], default="auto", help=mode_help)
    book_cmd("push", cmd_push, help="upload results to the material folder")
    book_cmd("pull", cmd_pull, help="download results others pushed")
    p = plain_cmd("sync", cmd_sync, help="on a server: pull from and push to the material folder, every book")
    p.add_argument("books", nargs="*", metavar="book", help="only these books (default: every book with a Proton path)")
    p.add_argument("--push-all", action="store_true", help="push even books that haven't changed since their last push")
    book_cmd("eval", cmd_eval, help="CER of every result vs ground truth")
    book_cmd("inventory", cmd_inventory)
    book_cmd("render", cmd_render, pages=True)
    book_cmd("checksum", cmd_checksum)
    plain_cmd("duplicates", cmd_duplicates, "books on this machine twice (same PDF, two ids)")
    p = plain_cmd("worker", cmd_worker, "OCR worker: read queued pages from a hosted server with the engines on this machine")
    p.add_argument("--server", help="the hosted server (default: AGAMA_SERVER in ~/.config/agama-mancha/hosted.env)")
    p.add_argument("--token", help="your listener token (default: AGAMA_TOKEN in that file)")
    p.add_argument("--engines", help="which engines to offer, e.g. surya or tesseract,surya (default: all installed)")
    p.add_argument("--batch", type=int, default=10, help="pages leased at a time")
    p.add_argument("--once", action="store_true", help="stop when the queue is empty instead of waiting")
    p = plain_cmd("fix-worker", cmd_fix_worker, "local AI for 'Fix with local AI': makes the edits proofreaders describe")
    p.add_argument("--server", help="the hosted server (default: AGAMA_SERVER in ~/.config/agama-mancha/hosted.env)")
    p.add_argument("--local", action="store_true", help="this machine's own viewer instead of a hosted server")
    p.add_argument("--port", type=int, default=8770, help="with --local: the viewer's port")
    p.add_argument("--token", help="your listener token (default: AGAMA_TOKEN in that file)")
    p.add_argument("--model", default=None, help="the Ollama model (default: qwen3.8:27b-mlx, or AMOCR_FIX_MODEL)")
    p.add_argument("--once", action="store_true", help="stop when nothing is waiting")
    p = plain_cmd("queue", cmd_queue, "on the server: queue a book for OCR workers, or show the queue")
    p.add_argument("book", nargs="?", help="the book to queue (omit to just show the queue)")
    p.add_argument("--engine", default="surya", choices=["tesseract", "surya"])
    p.add_argument("--pages", help="e.g. 221-238 (default: every page that needs it)")
    p = plain_cmd("member", cmd_member, "members of a hosted server: add, invite, token, list, remove")
    p.add_argument("action", choices=["add", "invite", "token", "list", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("--role", default="proofreader", choices=["reader", "proofreader", "validator", "coordinator", "admin"])
    p.add_argument("--port", type=int, default=8770, help="for the invite link it prints")
    p = plain_cmd("merge", cmd_merge, "merge a duplicate book into another: copy what's missing, then move it to data/trash")
    p.add_argument("dup", help="the book id to merge away")
    p.add_argument("keep", help="the book id to keep")
    p.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    p.add_argument("--show", type=int, default=15, help="how many files to list")
    p = book_cmd("estimate", cmd_estimate, pages=True, help="dry run for a paid engine")
    p.add_argument("--price-per-page", type=float, required=True)
    p.add_argument("--cap", type=float, required=True)

    args = ap.parse_args(argv)
    if not args.per_book:
        return args.fn(args)
    if args.fn is cmd_chat and (args.hosted or args.server):
        return _chat_remote(args)
    works = load_works()
    wid = resolve(works, args.work)
    if wid not in works:
        raise SystemExit(f"unknown book {args.work!r}; known: {', '.join(works) or 'none (use amocr fetch)'}")
    if wid != args.work:
        print(f"({args.work} was merged into {wid}; using {wid})", flush=True)
    args.fn(works[wid], args)


if __name__ == "__main__":
    main()
