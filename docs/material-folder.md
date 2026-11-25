# The material folder (proposal)

The OCR work here exists to produce the **library layer** of Agama Mancha (the
Sarvamnaya library design: originals, cleaned text and catalog, immutable and
versioned, with permanent IDs). The **material folder** on the shared drive is
where that material collects. This page proposes its layout. It's a proposal
for the team and the folder owner to approve; today the tool still writes the
per-book layout described in the coordinator guide.

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

## Proposed layout: by work, not by file path

```
Agama Mancha/
├── README.md                      how the material is organised
├── catalog/
│   └── works.csv                  one row per work (the catalog's CSV export)
└── works/
    └── SL-0001/                   permanent work ID, never a file name
        ├── work.json              catalog record (below)
        ├── card.md                work card: scope, out of scope, standpoint, relationships,
        │                          key terms, reliability notes, status (AI-drafted / verified)
        ├── glossary.json          the work's terms, to feed the shared concept glossary
        ├── pages/
        │   └── p0231/             every reading of page 231: engine, version, confidence,
        │                          lines with positions and type; never overwritten
        ├── text/
        │   ├── p0231.txt          current proofread text of the page
        │   └── p0231.history.jsonl  every earlier version: text, who, when, verified
        └── units/
            └── v003/              one build of the units, never changed after it's written
                ├── units.jsonl    one unit per line (below)
                └── build.json     date, tool version, pages verified at build time
```

### `work.json`

The design doc's catalog row: permanent work ID, title, author (of the root text
and of each commentary layer), lineage, period, language(s), script, edition
(publisher, year, editor), source file (library path and checksum, plus the
tool's `B-…` id, which is derived from the checksum), access tier
(open / restricted), rights notes, and status (pages done / proofread / verified).

### `units.jsonl`: what the librarian cites

```json
{"id": "SL-0001/13/34/mula", "work": "SL-0001", "chapter": 13, "verse": "34", "layer": "mula",
 "lang": "san", "text": "स्वदेहं चिन्तयेत्कृष्णं … ॥ ३४ ॥", "iast": "svadehaṃ cintayet kṛṣṇaṃ …",
 "pages": [231], "lines": [{"page": 231, "n": 3, "bbox": [404, 435, 1278, 503]}, …],
 "status": "verified", "source": "groundtruth"}
{"id": "SL-0001/13/34/hindi-mishra", "layer": "hindi-mishra", "explains": ["SL-0001/13/34/mula"], "lang": "hin", …}
```

- **IDs** follow the design: work/chapter/verse/layer. The root verse is `mula`; each
  commentary is its own layer, named for its author. A commentary passage covering
  verses 35–36 gets `…/35-36/hindi-mishra` and links to both verses.
- **Positions** point back to the page image, so any quotation can be shown on the scan.
- **Status** comes from the pages: `verified` only if every line was checked by a person;
  otherwise `draft`, which the librarian can still search but must flag.
- **Text** is NFC Devanagari, IAST generated from it; running headers, page numbers and
  signature marks are left out, words broken across lines are rejoined (each change logged).

## What exists today, and what's left

| Needed | Today | To build |
|---|---|---|
| Page readings with engine, version, confidence, positions | yes (Tesseract, Surya, Claude results; line and word boxes) | push them under `works/<id>/pages/` |
| Proofread text, never overwritten | saved per page; Proton keeps file revisions | an explicit `history.jsonl` on every save |
| Structure: header, verse (+ number), commentary (+ verses explained), footnote | yes, per line | chapter numbers; assembling units across pages (`amocr assemble`) |
| Work card | the book brief (`amocr brief`) is a first draft | the card's fields and status |
| Glossary | per book (`glossary.json`) | concept IDs with Devanagari, IAST, English and Hindi forms, shared across works |
| Catalog | `works.toml` (pilot) and each book's `book.json` | `catalog/works.csv` with the design's fields |
| Access tiers | `--restricted` stops every Claude step | carried into `work.json` and the units |

## Decisions for the team

1. **Location and owner**: `[OCR Mirror]/Agama Mancha`, or a new share; owned by the team.
2. **Work IDs**: who assigns `SL-…` numbers (one list, one person).
3. **Rights**: record each work's copyright status in `work.json`. Text that starts from
   Surya's reading may carry Surya's share-alike licence (see [engines.md](engines.md)).
4. **Restricted works**: which ones, so the tool never sends them to Claude.
5. **Commentary layer names**: e.g. `hindi-mishra` for Paramahaṃsa Miśra's Hindi commentary.
