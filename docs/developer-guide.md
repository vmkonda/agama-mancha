# Developer guide

## Layout

```
src/amocr/
  cli.py             all commands (argparse); `uv run amocr --help`
  catalog.py         Work (a book), ids from sha256, data/ layout, works.toml + book.json
  config.py          per-machine settings in data/config.toml (operator, Proton paths)
  pages.py           PDF inventory (text-layer check) and page rendering (pymupdf)
  textcheck.py       is an existing text layer real Devanagari/IAST or legacy-font junk?
  engines/           OCR engines; tesseract.py parses TSV into lines with confidence + bbox
  claude_session.py  Claude as an engine inside Claude Code: packets, result.json schema, import
  book.py            volunteer ops: add, fetch, export, merge, push, pull
  proton.py          wrapper around the official proton-drive CLI
  metrics.py         normalisation + character error rate
  server.py          local viewer API (127.0.0.1 only) + viewer.html
tests/               pytest; fake_proton.py stands in for the Proton CLI
.claude/skills/      ocr-book (volunteer flow), ocr-view (viewer)
CLAUDE.md            reading rules every Claude session follows
```

## Data (never committed)

```
data/config.toml
data/sources/<id>.pdf
data/works/<id>/book.json           books added with add/fetch (not in works.toml)
data/works/<id>/inventory.jsonl
data/works/<id>/pages/0231/image.png
data/works/<id>/pages/0231/ocr/<label>.{json,txt}
data/works/<id>/claude/p0231/       packet: band0-2.png, tesseract.txt, result.json
data/works/<id>/groundtruth/p0231.{txt,meta.json}
data/works/<id>/export/<stem>.amocr/  what push uploads
```

`AMOCR_DATA` overrides the data folder (the tests use it).

Results are append-only: a result file is never overwritten unless `--force`
is given, and `merge_in` never replaces a local file with a remote one. That
is what makes two volunteers pushing the same book safe for page results.
`book.json` and `book.txt` in the export are regenerated on every push, so
the last push wins for those summary files only.

## Result record

Every `pages/NNNN/ocr/<label>.json` has at least: `text`, `confidence`
(0–100 or null), `engine`, `engine_version`, `config`, `lines`, `work`,
`page`, `operator`, `amocr_version`, `created`. Tesseract lines carry
`conf` and `bbox` (image pixels); Claude lines carry `type` and `verse`, and
the record adds `regions`, `changes`, `uncertain`, `warnings`. Labels encode
engine, config and version, e.g. `tesseract-san+hin-psm3-5.5.4`,
`claude-code-correct-claude-opus-5-5`.

## Adding an OCR engine

1. Subclass `engines.base.Engine`: `version()`, `config()`, `run(image) -> OcrResult`,
   and a `label` that encodes config. Set `paid = True` and
   `price_per_page_usd` for paid engines.
2. Register it in `engines/__init__.py`.
3. Wire it into `cmd_ocr`. Paid engines must pass `amocr estimate` (budget cap)
   before running.
4. Run it on the pilot pages and compare with `amocr eval`.

Surya and a Google/Azure engine are the obvious next candidates.

## Proton Drive

`proton.py` shells out to `proton-drive` (official CLI, tested with 0.9.0):
`filesystem info|create-folder|download|upload`, with
`--file-conflict-strategy create-new-revision --folder-conflict-strategy merge` for
uploads. The CLI can't open public share links; folders must be shared to
the user's account and appear under `/shared-with-me/<share>/`. If the CLI's
arguments change, update `proton.py` and `tests/fake_proton.py` together.

## Safety rails (don't weaken without review)

- `proton.py` allow-lists CLI operations (read ops + create-folder + upload),
  confines writes to the results root, requires that root to exist, uploads
  with `create-new-revision`, and logs to `data/proton.log`.
- `.claude/hooks/guard_proton.py` (wired in `.claude/settings.json`) blocks
  Claude from running proton-drive writes/deletes, writing scripts that would,
  and editing `proton.py`, the hook or the settings. Start Claude with
  `AMOCR_DEV=1` to change those files deliberately.
- `test_safety.py` covers both. The hook is regex-based and bypassable by a
  determined user; the Proton permission split (viewer on originals) is the
  real boundary.

## Working together

`main` is protected, so several people can work at once without stepping on
each other:

1. Branch from an up-to-date `main`: `git switch -c <your-name>/<topic>`.
2. Push the branch and open a pull request (`gh pr create`).
3. CI runs the tests on Linux, Windows and macOS. All three must pass.
4. Another developer approves it. Changes to the safety rails (files listed in
   `.github/CODEOWNERS`) need the maintainer's approval.
5. Resolve review comments, then **squash and merge**. The branch is deleted
   automatically.

Nobody can push straight to `main`, force-push it or delete it. If `main`
moved while you worked, merge or rebase it into your branch; GitHub shows
when that's needed. Keep pull requests small and about one thing, so two
people rarely touch the same lines.

If you use Claude Code, ask it to work on a branch and open a pull request;
it shouldn't push to `main`.

## Tests

```sh
uv run pytest -q
```

`test_volunteer_flow.py` runs two volunteers through fetch → work → push →
fetch against a fake drive in a temp folder. No network, no Proton account.

## Conventions

- Keep the scans, book text and answer keys out of git; only code and docs (the repo is public).
- Never bind the viewer beyond 127.0.0.1. Remote use goes through `ssh -L`.
- Anything that sends pages off the machine must check `work.restricted`.
