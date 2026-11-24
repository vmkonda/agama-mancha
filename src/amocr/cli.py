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
  amocr push <book>                          upload results to OCR Mirror on Proton Drive
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
from .catalog import Work, load_works, sha256_of, verify_source
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
    if mode == "review":
        missing = [p for p in pages if not base_result(work, p)]
        if missing:
            print(f"Surya on {len(missing)} page(s) first ...")
            _run_engine(work, rows, missing, get_engine("surya"))
    return [(p, prep(work, p, _image(work, rows[p - 1]), mode)) for p in pages]


def _packet_help(mode: str) -> str:
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


# ---- commands that don't take a single book ---------------------------------


def cmd_status(args) -> None:
    from .book import page_status

    works = load_works()
    ids = [args.work] if args.work else list(works)
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
    print(f"next: `amocr ocr {w.id}` (Tesseract, all pages), then `amocr claude-next {w.id}`")


def cmd_init(args) -> None:
    cfg = cfgmod.load()
    for k in ("operator", "proton_root", "proton_bin", "mirror"):
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
            rr = results_root(cfg.proton_root, cfg.mirror)
            line(pd.exists(rr), f"results folder exists: {rr}", "ask the coordinator to create/share it; amocr never creates it")
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
        print("  (empty: ask the coordinator to share the library and OCR Mirror with your Proton account)")


def cmd_serve(args) -> None:
    from .server import serve

    serve(port=args.port, open_browser=not args.no_browser, page=args.open)


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
    p.add_argument("--mirror", help='results folder: a full path like "/shared-with-me/OCR Mirror", '
                   'or a folder name inside the team folder (default "OCR Mirror")')
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
    p = plain_cmd("serve", cmd_serve, "side-by-side viewer at http://127.0.0.1:8791")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--open", help="start at a page, e.g. B-1a2b3c4d5e/231")

    p = book_cmd("ocr", cmd_ocr, pages=True, help="OCR pages with Tesseract or Surya (default: all pages)")
    p.add_argument("--engine", default="tesseract", choices=["tesseract", "surya"],
                   help="surya: local Surya 2.5 model (optional install, see docs/engines.md)")
    p.add_argument("--langs", default="san+hin")
    p.add_argument("--psm", type=int, default=3)
    p.add_argument("--force", action="store_true", help="redo pages that already have a result")
    mode_help = "review: Claude checks Surya's reading line by line (fewer tokens); bands: Claude reads whole-page strips; auto: review if Surya is installed"
    p = book_cmd("claude-next", cmd_claude_next, help="prepare the next pages for Claude")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--mode", choices=["auto", "review", "bands"], default="auto", help=mode_help)
    p = book_cmd("claude-import", cmd_claude_import, pages=True, help="store Claude's finished pages")
    p.add_argument("--ready", action="store_true", help="every page with a result.json not yet imported")
    p.add_argument("--force", action="store_true")
    p = book_cmd("claude-prep", cmd_claude_prep, pages=True, help="prepare specific pages for Claude")
    p.add_argument("--mode", choices=["auto", "review", "bands"], default="auto", help=mode_help)
    book_cmd("push", cmd_push, help="upload results to the team's OCR Mirror")
    book_cmd("pull", cmd_pull, help="download results others pushed")
    book_cmd("eval", cmd_eval, help="CER of every result vs ground truth")
    book_cmd("inventory", cmd_inventory)
    book_cmd("render", cmd_render, pages=True)
    book_cmd("checksum", cmd_checksum)
    p = book_cmd("estimate", cmd_estimate, pages=True, help="dry run for a paid engine")
    p.add_argument("--price-per-page", type=float, required=True)
    p.add_argument("--cap", type=float, required=True)

    args = ap.parse_args(argv)
    if not args.per_book:
        return args.fn(args)
    works = load_works()
    if args.work not in works:
        raise SystemExit(f"unknown book {args.work!r}; known: {', '.join(works) or 'none (use amocr fetch)'}")
    args.fn(works[args.work], args)


if __name__ == "__main__":
    main()
