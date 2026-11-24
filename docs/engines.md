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
