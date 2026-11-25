# The material folder

The OCR work here exists to produce the **library layer** of Agama Mancha (the
Sarvamnaya library design: originals, cleaned text and catalog, immutable and
versioned, with permanent IDs). The **material folder** on the shared drive is
where that material collects. **Everything in it is for Vimarsha's internal
use**; nothing is published.

## Where it lives

A folder volunteers can write to, separate from the library of originals (which
stays view-only for them). Proposed: **`[OCR Mirror]/Agama Mancha`**. The team's
`[OCR Mirror]` is already a separate share that volunteers can be editors of; its
existing contents (the team's ocrmypdf PDFs) stay as they are. A share of its own
works just as well. Either way the owner should be the team, not one volunteer.

Proton gives one role for a whole share: editors of `[OCR Mirror]` could change
the PDFs in it too. The tool only ever writes inside the material folder.

Set it with `amocr init --material "/shared-with-me/[OCR Mirror]/Agama Mancha"`.
The tool never creates that folder and refuses to run without the setting.

## Layout: legible names, like the library

Each book's material sits at the same path as its PDF in the library, in a folder
named after the PDF, so anyone can find a book's text by its name:

```
Agama Mancha/
├── catalog/
│   ├── catalog.json               every PDF in the library (amocr catalog refresh)
│   ├── changes.jsonl              what each refresh found new, moved, changed or gone
│   ├── board/<person>.json        each person's claims and their books' progress
│   └── inventory/<person>.json    each person's text-layer measurements (amocr catalog inventory)
└── Texts/Agamas/Shri Malini Vijayottara Tantra/
    └── Shri Malini Vijayottara Tantra (Hindi, Paramhansa Mishra).amocr/
        ├── book.json              the book's record and page status (planned: work.json, below)
        ├── book.txt               every page's best text, one after another
        ├── pages/
        │   └── p0231/             every reading of page 231: engine, version, confidence,
        │                          lines with positions and type; never overwritten
        ├── groundtruth/
        │   └── p0231.txt, .meta.json   the proofread text, who saved it, whether verified
        └── units/
            └── v002/              one build of the units, never changed after it's written
                ├── units.jsonl    one unit per line (below)
                └── build.json     date, tool version, chapters, verse numbers to check
```

Planned, not built yet: `work.json` (the design's catalog record), `card.md` (the work
card), `glossary.json` in the shared folder, and `text/` with a `history.jsonl` of every
earlier version of each page.

Folder names may change when the library is reorganised; the permanent work ID
(`SL-0001`) in `work.json` doesn't, and units and citations use it, never the path.

### `work.json`

The design doc's catalog row: permanent work ID, title, author (of the root text
and of each commentary layer), lineage, period, language(s), script, edition
(publisher, year, editor), source file (library path and checksum, plus the
tool's `B-…` id, which is derived from the checksum), access tier
(open / restricted), rights notes, and status (pages done / proofread / verified).

### `units.jsonl`: what the librarian cites

```json
{"id": "SL-0001/13/34/mula", "work": "SL-0001", "chapter": 13, "verse": "34", "layer": "mula",
 "lang": "san", "text": "स्वदेहं चिन्तयेत्कृष्णं … ॥ ३४ ॥", "iast": "svadehaṃ cintayetkṛṣṇaṃ … || 34 ||",
 "pages": [231], "lines": [{"page": 231, "n": 3, "bbox": [404, 435, 1278, 503]}, …],
 "status": "verified", "source": ["groundtruth"], "types": "guessed"}
{"id": "SL-0001/13/34/hindi-mishra", "layer": "hindi-mishra", "explains": ["SL-0001/13/34/mula"], "lang": "hin", …}
```

- **IDs** follow the design: work/chapter/verse/layer. The root verse is `mula`; each
  commentary is its own layer, named for its author. A commentary passage covering
  verses 35–36 gets `…/35-36/hindi-mishra` and links to both verses.
- **Positions** point back to the page image, so any quotation can be shown on the scan.
- **Status** comes from the pages: `verified` only if every line was checked by a person;
  otherwise `draft`, which the librarian can still search but must flag.
- **Text** is NFC Devanagari, IAST generated from it; running headers, page numbers and
  signature marks are left out, words broken across lines with a hyphen are rejoined (the build counts them).

## What exists today, and what's left

| Needed | Today | To build |
|---|---|---|
| Page readings with engine, version, confidence, positions | yes (Tesseract, Surya, Claude results; line and word boxes); `push` shares them in `pages/` | |
| Proofread text, never overwritten | saved per page; Proton keeps file revisions | an explicit `history.jsonl` on every save |
| Structure: header, verse (+ number), commentary (+ verses explained), footnote | yes: `amocr assemble` classes lines from the text, finds chapters, builds units across pages | unit types confirmed by a person (today `types: "guessed"`) |
| Work card | the book brief (`amocr brief`) is a first draft | the card's fields and status |
| Glossary | per book (`glossary.json`) | concept IDs with Devanagari, IAST, English and Hindi forms, shared across works |
| Catalog | `works.toml` (pilot) and each book's `book.json` | `catalog/works.csv` with the design's fields |
| Access tiers | `--restricted` stops every Claude step | carried into `work.json` and the units |

## Decisions for the team

Decided (2026-11-25): the material folder is **`[OCR Mirror]/Agama Mancha`**, folders use
**legible names** (the PDF's), and all output is for **Vimarsha's internal use**.

Still open:
1. **Work IDs**: who assigns `SL-…` numbers (one list, one person).
2. **Rights notes**: record each work's copyright status in `work.json`, so that any later
   wish to share outside Vimarsha can be checked work by work.
3. **Restricted works**: which ones, so the tool never sends them to Claude.
4. **Commentary layer names**: e.g. `hindi-mishra` for Paramahaṃsa Miśra's Hindi commentary.
