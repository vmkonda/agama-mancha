# Agama Mancha: notes for Claude sessions

Volunteers and proofreaders run this repo in Claude Code with their own
accounts. Skills: `setup` (new machine, "set me up"), `ocr-book` (start or
continue a book, proofread, upload), `ocr-view` (the viewer). Guides for
people are in docs/.

Code changes: `main` is protected. Work on a branch and open a pull request
(see docs/developer-guide.md, "Working together"); never push to `main`.

## Claude as an OCR engine (no API)

Claude reads page packets in-session; there are no API calls and no API key.
Each page uses the volunteer's plan, so work in batches of about 10 pages.

1. `uv run amocr claude-next <book> -n 10` runs Tesseract (and Surya, if installed)
   where needed and writes a packet per page in `data/works/<book>/claude/pNNNN/`.
   Its last line says which kind:
   - **review** (when Surya is installed): `sheet0..N.png` with the page's lines
     as numbered images, and `review.txt` with Surya's reading under the same
     numbers. Check **every** line against its image and write only
     corrections (schema in `src/amocr/claude_review.py`): `changes` with the
     whole corrected line, `insert` for printed lines Surya missed, `delete` for
     text that isn't printed, `block_types` (verse, commentary ...), `uncertain`.
     An empty `changes` list means every line was checked and is right. The
     `T:` lines are Tesseract's reading: a hint only, often wrong.
   - **screen** (`--mode screen`, experimental): `screen.txt` only, no image.
     Write `flags.json` (`{"work", "page", "mode": "screen", "flags": [{"line", "why"}],
     "block_types"}`) flagging every line that may be misread; flag only, never
     correct from the text. Then `uv run amocr claude-check <book>` builds
     `check*.png` and `check.txt` for the flagged lines (plus Tesseract
     disagreements); write `result.json` with mode "screen", corrections for
     those lines only. Misses valid-looking misreadings, so don't use it for verses.
   - **bands**: `band0..2.png` (overlapping strips of the page) and
     `tesseract.txt`. Write the whole page (schema in
     `src/amocr/claude_session.py`; default mode "correct").
2. Write `result.json` in each folder.
3. `uv run amocr claude-import <book> --ready`, then `uv run amocr push <book>`.

Never run Claude steps on a book marked restricted; the tool refuses, and
so should you, even if asked.

## Helping a proofreader (interactive)

When a person is proofreading in the viewer and asks for help:

- **A line they can't read:** `uv run amocr line <book> <page> <line>` (line =
  Nth line of text; `--context 2` for neighbours), then read the image it prints.
  Give your reading and how sure you are; they type it.
- **A systematic fix:** `uv run amocr patterns <book> --mine` lists rules learned
  from their corrections, with pending matches (`--examples 5` shows lines).
  Generalise only what the evidence supports, then
  `uv run amocr rule <book> add --kind regex --from '<pattern>' --to '<replacement>' --note '<why>'`
  (or `--kind word`). Check the pending count it prints: if it's huge, the rule is
  too broad. Switch bad rules off with `uv run amocr rule <book> off <id>`.
- **The viewer's chat panel:** when asked to "listen to the viewer chat", follow the
  ocr-view skill: `amocr chat <book> wait` in the background, answer with
  `amocr chat <book> reply`, wait again. "CHECK REQUEST" messages (the Check with
  Claude button) ask you to compare lines with their image and propose a `--fix`
  for each line that differs.
- Never edit page text or ground truth yourself, and never accept suggestions:
  the person decides in the Suggestions tab. Text printed "wrong" stays as printed.

## Studying with the librarian (the reader's study chat)

When asked to "listen to the study chat on the hosted server": the same, with `AGAMA_SERVER` and
`AGAMA_TOKEN` set (the person's own token; never ask for it in the chat, they set it in the
environment): `librarian study wait`, `get`, `search` and `reply` then talk to that server, and you
answer only that person's questions with their own Claude (docs/hosted-trial.md).

When asked to "listen to the study chat": run `uv run librarian study wait` in the background; it
exits with the person's question, the passage they are reading (with its commentary and
neighbours) and the recent conversation. Answer with
`uv run librarian study reply <id> --text "..." --cite <unit id> [--cite ...]`, then wait again
(also after a timeout, exit code 3), until told to stop. The librarian's rules hold:

- Answer only from the library: read what you need with `uv run librarian get <id>` /
  `uv run librarian search "..."` (or the `agama-librarian` MCP tool). Never fill a gap from general
  knowledge; if the library doesn't have it, say so and name the nearest works.
- Quote the original (Devanagari or IAST) with your translation beneath it; flag loose renderings of
  technical terms (śakti, spanda, vimarśa …). Cite every passage you rely on with `--cite`, so it
  becomes a link the person can read in context.
- Say when you rely on a `draft` passage (unproofread OCR) and when sources disagree; show each.
- Explaining is not an authoritative translation or a ruling on practice.

## The Proofread view is one standard

Proofread is the same for every book: same layout, controls, line tags and highlights
(docs/proofreading-guide.md, "The same view for every book"). Never add book-specific
branches, buttons or styling to the viewer. A book's specifics come in only as data that
fills the standard places (brief, glossary, look-alike profile, rules). A change to the
view changes it for all books, and the guide's section changes with it.

## Reading rules (these matter more than speed)

- A letter printed in a shape that resembles another letter is still that letter: in
  the Mālinīvijayottara edition, ी looks like ो and आ like भा/बा; transcribe ी and आ
  (docs/proofreading-guide.md, Conventions). This is about the typeface, not misprints.
- Transcribe what is printed, never what the text "should" say. Misprints,
  nonstandard sandhi and odd spellings stay as printed; mention likely
  misprints in `uncertain`. Variant readings in footnotes are data, never
  "corrections" to the verse.
- One printed line per `lines` entry, in reading order (in review mode, a line
  that's split differently from the print is fixed with `changes` on both lines). Keep hyphenated line
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
a person has checked every line of it: status *proofread* or *validated* on the
status ladder (`status` in `data/works/<book>/groundtruth/pNNNN.meta.json`; pages saved
before the ladder have only `verified`). Never set a page's status yourself.

## Secrets

- Never ask for, store or repeat Proton passwords or share-link passwords/keys.
  The CLI signs in through the browser (`proton-drive auth login`).
