# agama-mancha-ocr: notes for Claude sessions

Volunteers and proofreaders run this repo in Claude Code with their own
accounts. Skills: `setup` (new machine, "set me up"), `ocr-book` (start or
continue a book, proofread, upload), `ocr-view` (the viewer). Guides for
people are in docs/.

Code changes: `main` is protected. Work on a branch and open a pull request
(see docs/developer-guide.md, "Working together"); never push to `main`.

## Claude as an OCR engine (no API)

Claude reads page packets in-session; there are no API calls and no API key.
Each page uses the volunteer's plan, so work in batches of about 10 pages.

1. `uv run amocr claude-next <book> -n 10` runs Tesseract where needed and writes
   `data/works/<book>/claude/pNNNN/`: `band0..2.png` (overlapping top, middle and
   bottom of the page) and `tesseract.txt`.
2. Read the bands and write `result.json` in each folder (schema in
   `src/amocr/claude_session.py`; default mode "correct").
3. `uv run amocr claude-import <book> --ready`, then `uv run amocr push <book>`.

Never run Claude steps on a book marked restricted; the tool refuses, and
so should you, even if asked.

## Reading rules (these matter more than speed)

- Transcribe what is printed, never what the text "should" say. Misprints,
  nonstandard sandhi and odd spellings stay as printed; mention likely
  misprints in `uncertain`. Variant readings in footnotes are data, never
  "corrections" to the verse.
- One printed line per `lines` entry, in reading order. Keep hyphenated line
  breaks as printed (`प्रति-` then `निधियों`).
- Keep headers, page numbers, footnote markers (as digits after the word) and
  signature marks (मा० वि०—३).
- Anything not readable with confidence goes into `uncertain` and is still
  transcribed as best read; never drop a line.
- Correct mode: start from `tesseract.txt`; every edit goes into `changes`
  with the reason. Direct mode: ignore `tesseract.txt`.
- Do not read ground truth files (`data/works/<book>/groundtruth/`) while transcribing.
- Proofreading conventions for people are in docs/proofreading-guide.md; keep
  the two consistent.

## Ground truth

Claude-drafted ground truth must not be used to score a Claude engine until
a person has verified it (the viewer's "verified" tick, stored in
`data/works/<book>/groundtruth/pNNNN.meta.json`).

## Secrets

- Never ask for, store or repeat Proton passwords or share-link passwords/keys.
  The CLI signs in through the browser (`proton-drive auth login`).
