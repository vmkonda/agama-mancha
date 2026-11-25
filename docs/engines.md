# OCR engines

amocr can read a page with three engines. Every result is kept side by side
(`pages/pNNNN/ocr/<engine>.json`), so they can be compared in the viewer and
scored against verified ground truth with `amocr eval`.

| Engine | Runs | Cost | Speed (Mac Studio, M4 Max) | Notes |
|---|---|---|---|---|
| Tesseract (`san+hin`) | locally | free | ~1 s per page | The baseline. Weak on conjuncts and Sanskrit verses. |
| Surya 2.5 | locally | free (see licence) | ~11 s per page, ~1.5 h per 460-page book | Close to Claude on the pilot pages tried so far. Optional install. |
| Claude | in a volunteer's Claude Code session | the volunteer's Claude plan | minutes per page, in batches of ~10 | Best reading so far; limited by plan usage. |

On one pilot page (p231), against Claude's reading (not yet verified by a
person, so this is not an error rate): Tesseract differed by 6.4% of
characters, Surya by 1.1%. Measure on verified ground truth before relying on
these numbers.

## Claude review mode

When Surya is installed, `amocr claude-next` prepares **review** packets by
default: the page's lines as numbered images, plus Surya's reading under the
same numbers. Claude checks every line against its image and writes only the
corrections, instead of transcribing the whole page again. The import applies
them to Surya's lines, so the result keeps a box on the scan for every line.

On p231 of the pilot book, review mode made 5 corrections (footnote markers, one
consonant, two words) and roughly halved Claude's tokens for the page, almost
all of it in what Claude writes. The line images still cover the whole text
area, so image tokens are about the same as whole-page strips. `--mode bands`
gives the old behaviour.

### Screen mode (experimental)

`--mode screen` goes further: Claude first reads only Surya's text and flags
lines that may be misread, then `amocr claude-check` builds images of just those
lines (plus lines where Tesseract disagrees a lot) for Claude to correct.

Compared with a full review on pages 232-235 of the pilot book (Claude did both;
nothing verified by a person yet):

| | Full review | Screen |
|---|---|---|
| Lines checked against an image | 120 of 120 | 52 of 120 (41 flagged from the text, 11 by Tesseract) |
| Corrections found | 30 | 28 |
| Image tokens, 4 pages | ~17,700 | ~8,400 |
| Text read | each page once | each page once, plus the check list |

The two misses are the expected blind spot, readings that look valid as text:
a dropped द in a verse (तद्वद्वादश for printed तद्वद्द्वादश) and सांचा for
printed साँचा. In total, screen mode used roughly a quarter fewer tokens per page
than a full review. It isn't the default: verses need every line checked.

In this typeface ी often looks like ो (भो, सकतो, शरोर). Surya sometimes reads
the intended ी and sometimes the shape; proofreaders should expect this.

Surya-derived text is still Surya output for licence purposes (see below).

## Suspect lines: what to check first (free, text only)

`amocr suspects <book>` scores every line from the text alone, with no Claude and no
tokens:

| Signal | What it looks for |
|---|---|
| look-alike | a word that is rare in this book while a look-alike of it is common (देवो/देवी, बादि/आदि, अमराचित/अमरार्चित), whole words first, then a character model trained on the book's own text (catches compounds) |
| metre | a verse line with the wrong syllable count |
| verse number | a verse number out of sequence |
| Tesseract | Tesseract reads the same line differently |
| rare | a word that occurs once and looks unusual for this book |

**Which letters look alike depends on the typeface**, so nothing is built in. Each
book has a profile (`amocr profile <book>`) with its look-alike pairs and metre,
and pairs people correct at least twice are learned automatically. A new book
starts with the general signals only.

Measured on the Mālinīvijayottara pilot, against the 42 lines corrected so far on
8 pages:

| Setting | Known errors caught | Lines flagged |
|---|---|---|
| score ≥ 3 (look-alike, verse number) | 9 of 42 | 18 of 219, half of them real errors |
| score ≥ 2 (adds Tesseract disagreement) | 36 of 42 | 117 of 219 |

So the confident look-alikes are good Suggestions (`--add-rules`), and score ≥ 2
roughly halves the lines that need an image check while keeping most errors. It
doesn't replace reading: the misses are single wrong letters that form valid
words, and footnote markers. These numbers come from one book; measure again on
each new one (`amocr suspects <book> --eval`).

## Surya

### Install (optional)

```
uv sync --extra surya
```

Surya runs its model through a local inference server that it starts and stops
by itself for each run. Nothing is exposed to the network, and nobody else
connects to it.

- **Mac with Apple Silicon:** uses `llama-server` with Metal. It comes with
  Ollama, or `brew install llama.cpp`.
- **Linux with an NVIDIA GPU:** uses vLLM.
- **Windows with an NVIDIA GPU:** `llama-server` with CUDA (untested).
- **No usable GPU:** `llama-server` on the CPU works but is much slower.

The model (about 1.5 GB) downloads on first use into `~/.cache/huggingface`.

### Run

```
uv run amocr ocr <book> --engine surya              # every page
uv run amocr ocr <book> --engine surya --pages 51-60
```

Then `uv run amocr push <book>` as usual. One fast machine can run Surya for
the team: everyone else pulls the results and proofreads, and needs neither
Surya nor a GPU.

### Positions and structure

Every Surya line has its own box on the scan, and every word has one too: they
come from Tesseract's word boxes, matched to Surya's words character by
character. Where Tesseract found nothing, the box is estimated and marked
`"box": "estimated"`. On six pilot pages: every line had its own Tesseract box,
and 3 of 1,911 words were estimated.

Each line also says what it is: `header`, `verse` (with the `verse` number it
belongs to; a half-verse at the bottom of a page has none), `commentary` (with
the verses it `explains`, from its closing `॥ ३५-३६ ॥`), `footnote` or
`signature`. Surya labels headers and footnotes itself; verse versus commentary
is decided by rule: lines ending in daṇḍas and no Hindi words. Claude's review
can correct any of them.

### How the output is shaped

Surya reads the whole page and returns blocks (header, verses, commentary,
footnotes) in reading order, with footnote markers as plain digits. Verses keep
their printed line breaks; prose paragraphs come back as one long line, so
amocr splits each paragraph again along Tesseract's line boxes inside the same
block. That keeps one printed line per line (the proofreading convention) and
gives each line a box on the scan for the viewer. Where line counts can't be
matched, the line gets the whole block's box.

Known weak spots on the pilot pages: occasional single-character misreads in
verses, and footnote markers that can be missing or misnumbered. Hyphenated
words broken across printed lines come back joined.

### Licence: read before using Surya on a book

Checked 2026-11-24 against the
[repository](https://github.com/datalab-to/surya) and its
[`MODEL_LICENSE`](https://github.com/datalab-to/surya/blob/master/MODEL_LICENSE).
This is a summary, not legal advice.

- **Code:** Apache-2.0. amocr only calls Surya as a separately installed
  optional package and doesn't copy or modify its code, which this repo's MIT
  licence is fine with.
- **Model weights:** "AI Pubs Open RAIL-M License (Modified)". It applies to
  whoever runs the model, and it has terms that matter for a library:
  - **Who may use it free:** the commercial limits apply to anyone (or their
    employer or affiliated entity) with more than $5M revenue or funding in
    the prior year, unless the use is limited to personal use or research. A
    volunteer library with no revenue is under that limit. It's unclear how
    "your employer" applies to volunteers who work for large companies.
  - **Competitors:** no use by anyone offering a product or service that
    competes with Datalab's (they sell OCR and document conversion).
  - **Attribution (section 7):** "in connection with any Output", give credit
    to the licensor, link to the model and include a copy of the licence.
  - **Share-alike (section 8):** the licence must be applied "to the Output and
    any derivatives, changes or improvements to or of the Output". Read
    literally, text that starts from Surya's reading, proofread or not, would
    have to be published under this licence, with its use restrictions.
  - **Output rights (section 6):** Datalab claims no rights in the output.

**Decision for the team before publishing anything Surya produced:** the
share-alike clause may conflict with how the library wants to license its texts
(for example public domain or a Creative Commons licence). Options: accept the
licence for Surya-derived text, use Surya only as a private aid and publish
text proofread from another engine's reading, or ask Datalab
(hi@datalab.to) how the clauses apply to a non-commercial digital library.
Until that's decided, keep Surya results internal to the team.
