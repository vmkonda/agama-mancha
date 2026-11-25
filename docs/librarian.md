# The librarian: first end-to-end slice

The design doc's five layers, built thinly over the Trika core from published e-texts, so the whole
idea can be tested before the OCR of any book is finished. Everything runs on this machine; the only
Claude use is the session that asks the questions.

| Layer | What exists now |
|---|---|
| Library | 10 GRETIL e-texts as works `ET-0001`…`ET-0010` (provisional ids until the team's `SL-` list), units `work/chapter/verse/layer` in Devanagari with IAST, status `edition`; plus the assembled units of OCR'd books (Mālinī `SL-0001`, with Miśra's Hindi commentary, status `draft`) |
| Preprocessing | units from the editions' own structure: verses, sūtras, Bhāskara's vārttika and Utpala's vṛtti linked to what they explain, prose split near 400 words |
| Index | LanceDB: keyword search on IAST folded to plain letters plus bge-m3 meaning search (local Ollama), merged by rank fusion. Ids and search text only; passages are read from the library |
| Curation | not yet (work cards, concept glossary): the design builds it after the index |
| Librarian | an MCP tool for Claude Code: `search`, `get_unit` (with the commentary on a unit), `list_works`, with the design's grounding rules as its instructions |

## The Trika core

| Id | Work | Units |
|---|---|---|
| ET-0001 | Mālinīvijayottaratantra | 1,292 |
| ET-0002 | Vijñānabhairava | 174 |
| ET-0003 | Śivasūtra with Bhāskara's Vārttika | 833 |
| ET-0004 | Spandakārikā | 57 |
| ET-0005 | Tantrasāra | 46 (prose passages) |
| ET-0006 | Tantrāloka | 5,901 |
| ET-0007 | Pratyabhijñāhṛdaya | 167 |
| ET-0008 | Īśvarapratyabhijñākārikā with Vṛtti | 372 |
| ET-0009 | Paramārthasāra | 105 |
| ET-0010 | Svacchandatantra | 3,680 |

GRETIL's e-texts are licensed CC BY-NC-SA (non-commercial; internal use is fine); they live in
`data/etexts/` and `data/library/`, never in the repo. Citations name GRETIL's edition, which is not
the team's printed copy.

## Using it

```sh
uv sync --extra librarian                  # LanceDB and the MCP library
ollama pull bge-m3                         # the embedding model (local)
uv run librarian ingest data/etexts/gretil/*.xml
uv run librarian build                     # about 10 minutes for 15,000 units
uv run librarian search "spanda"           # or Devanagari, or English
uv run librarian get ET-0003/1/1/mula      # a sūtra with the vārttika on it
```

In Claude Code in this folder, the `agama-librarian` MCP tool (`.mcp.json`) gives Claude `search`,
`get_unit` and `list_works`; approve it once when asked. Ask a question and Claude answers from the
retrieved passages only, with citations.

## In the app

The **Librarian** page (next to Library and Proofreading; `amocr serve` started with
`uv run --extra librarian amocr serve`) has three tabs. (The **Library** page lists the team's PDFs on
the drive; the works the librarian can search, e-texts included, are under **Librarian → Works**.)

- **Works** lists every work in the library (e-texts and OCR'd books) with its id, kind, number of
  passages, source edition and licence; **Read** opens it at the first chapter.

- **Search** reads passages in any language or script, filtered by work or layer, each with its
  work, id, status (`edition` or `draft`), printed pages, and how it was found; *Context* opens the
  commentary on it and its neighbours; *Copy citation* copies the passage with its id. Asking a
  question and getting a cited answer happens in Claude Code, through the MCP tool.
- **Read in context** (on every passage) opens the whole chapter with the cited passage outlined and
  the commentary where the edition puts it, with the previous and next chapters. The way back to the
  source: for the team's printed books, *scan p. N* opens that page in the viewer with the cited lines
  outlined on the scan; for e-texts, the edition and licence, and a link to the GRETIL file. A reading
  can be shared as a link: `/librarian#read=<unit id>`.
- **Study with Claude** (a button in the reader) opens a panel beside the text. Click a passage to
  put it in focus, ask about it (a translation, a term, what the commentary says, where else the
  idea appears), and Claude answers from the library only, quoting the original with a translation;
  every passage it cites is a link that opens in the reader. As with the proofreading chat, the app
  can't call Claude: a Claude Code session in the project answers, after being asked to "listen to the
  study chat" (`librarian study wait` / `reply`; conversations in `data/library/study/`).
- **Evaluation** is the yardstick: 20 questions Claude drafted across the design's types (lookup,
  concept, cross-language, commentary, not in the library), each with the passages it thinks answer
  it. The owner corrects the expected unit ids (or *adds* one from the top results), approves or drops
  each question, and runs the evaluation after every rebuild (`uv run librarian eval` does the same).
  Questions and runs are in `data/library/eval/`.

First baseline (2026-11-25, unreviewed draft answers): 11 of 18 scored questions have a correct
passage in the top 10 (lookup 5/5, concept 3/5, cross-language 2/5, commentary 1/3). Some misses are
the draft answers being too narrow: for the vāyavī dhāraṇā the top result is Miśra's commentary on
13.34, a good answer the draft didn't list.

## Not yet

- Work cards and the concept glossary (cross-language questions lean on meaning search until then).
- Sandhi splitting and lemmas in the search fields.
- The owner's review of the evaluation set (the answers are Claude's drafts until approved).
- Mapping verse numbers between GRETIL's Mālinī and the printed edition, so the Hindi commentary links
  to the GRETIL mūla.
