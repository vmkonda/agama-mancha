# agama-mancha-ocr

Turns scanned Sanskrit and Hindi books into accurate, checkable text, page by
page, as a team. Part of Agama Mancha, a library of the Sarvāmnāya literature.

- **Tesseract** reads every page for free.
- **Claude**, run by each volunteer in Claude Code with their own account,
  re-reads pages: it fixes misreadings, labels verses, commentary and
  footnotes, and lists every change it made and everything it was unsure of.
- **Proofreaders** check pages against the print in a side-by-side viewer.
  Their verified pages measure the accuracy of every method.
- **Proton Drive** is the shared store: results go to the team's
  *material folder* for Agama Mancha, never to the originals, so anyone can continue a book.

## Which guide is for you

| You are… | Read |
|---|---|
| A volunteer who wants to OCR books (no programming needed) | [Volunteer guide](docs/volunteer-guide.md) |
| A scholar or paṇḍita checking text against the print | [Proofreading guide](docs/proofreading-guide.md) |
| Owner of the team's Proton Drive folders: setup, trust model, decisions | [Drive setup](docs/drive-setup.md) |
| Coordinating the team: access, assigning books, restricted texts | [Coordinator guide](docs/coordinator-guide.md) |
| A developer working on the code | [Developer guide](docs/developer-guide.md) |
| Choosing or installing an OCR engine (Tesseract, Surya, Claude), and their licences | [Engines](docs/engines.md) |
| What the OCR produces for Agama Mancha, and where it goes on the drive | [Material folder](docs/material-folder.md) |

## The short version

```sh
git clone https://github.com/vmkonda/agama-mancha-ocr.git
cd agama-mancha-ocr
claude          # then say: "Set me up"
```

Claude installs what's missing, downloads the Proton Drive tool and the
pinned Sanskrit/Hindi models, walks you through the Proton sign-in, and saves
your name and folders. After that:

- "Start OCR on /shared-with-me/<library>/<path>/book.pdf"
- "Continue OCR on book <id>"
- "I want to proofread book <id>"

Everything is also available as plain commands (`uv run amocr --help`).

## Relation to the team's ocrmypdf method

The team's `ocrmypdf -l iast+eng+san` searchable PDFs stay as they are. This
tool adds per-page text with confidence, structure and credits, and measures
methods against proofread pages. On the first pilot page (Mālinīvijayottara
with Hindi commentary), `iast+eng+san` had 13.7% character errors and
`san+hin` 5.7%. That's one page and a draft answer key, so treat it as a
signal, not a result.

## Ground rules

- No book scans or text in git (`data/` is ignored); books live on Proton Drive.
- Restricted texts (`--restricted`) never go to Claude.
- The viewer listens on 127.0.0.1 only; over SSH use a tunnel.
- Transcribe what is printed. Variants stay in footnotes. Misprints stay, with a note.

## License

MIT, see [LICENSE](LICENSE). The license covers the code and documentation only; the books processed with it keep their own copyright.
