# Plan: from OCR tool to the team's workbench

Agreed 2026-11-25. The goal: one application in which anyone on the team sees every
book in the library, picks one to work on, and sees who is working on what and how far
each book has got. There is no server: the **material folder** on Proton Drive is the
shared board, and every volunteer's copy of the app reads it and writes only its own
small files there.

The library today: **976 PDFs, 32.8 GB** (Authors 325, Texts 336, Studies 173,
Miscellaneous 66, Reference 60, Kula Internal Documents 15).

## Phases

| Phase | What | Status |
|---|---|---|
| A | **Catalog** of every PDF, with refresh; the **Library** page | done (#12) |
| B | **Claims, stages and progress** per book; *Work on this* and *Release* | done (#13) |
| C | **Inventory** per book: text layer, page count, script (which need OCR) | done (#14) |
| D | **Assemble** units into the material folder layout ([material-folder.md](material-folder.md)) | done (#15) |

### A. Catalog and Library page

- `amocr catalog refresh` lists the library (read-only) and updates
  `<material folder>/catalog/catalog.json`: one entry per PDF with path, name, folder,
  size and date. Facts learned later (checksum, pages, script, SL id) are added by
  later phases.
- **Refresh is safe to repeat.** New PDFs are added; removed ones are marked *gone*,
  never deleted; moved or renamed ones are matched by name and size (or checksum) and
  keep their history (`moved_from`); changed ones (same path, new size) are flagged.
  Each refresh appends a line to `catalog/changes.jsonl`.
- **When it runs**: `amocr start` refreshes if the catalog is more than a day old; the
  Library page has a *Refresh* button; one always-on machine can run it nightly.
- **Two people refreshing at once is harmless**: the catalog only reflects the library
  listing. What people do lives in each book's own status file, which a refresh never
  touches.
- The **Library page** lists every book, with search and filters (folder, new, gone),
  shows when the catalog was last refreshed and by whom, and opens books already on
  this machine.

### B. Claims, stages, progress

- **The board**: `<material folder>/catalog/board/<person>.json`, one small file per
  person with their claims and the progress of every book on their machine (page counts
  per step, stage). Nobody edits a shared file, so two people never overwrite each
  other; everyone's app reads all the files and merges them. Books are keyed by the
  PDF's checksum, so claims survive the library being reorganised. (The plan first had
  one `status.json` per book; with no locks on Proton, two people saving it at once
  would lose one of the saves.)
- Stages: listed → inventoried → read by Surya → reviewed → proofreading → verified →
  assembled. Updated automatically as people work.
- *Work on this* reads the board, writes the claim, reads the board back to confirm
  (Proton has no locks); the earliest claim wins, and a later one withdraws itself. It
  also downloads the PDF if it isn't on this machine. A claim with no activity for 14
  days shows as stale; anyone may then release it, and the release is recorded in the
  releaser's own file. Whole books first; page ranges later.
- Progress is shared on every `amocr push` and `amocr start`, and with *Sync board*.
- Commands: `amocr board` (show), `amocr board sync`, `amocr board claim <book>`,
  `amocr board release <book> [--why …]`.

### C. Inventory

The design doc's first OCR step: per PDF, count extractable text and test whether it is
valid Devanagari or IAST. Books with a good text layer need no OCR. Runs when a book is
fetched, or in bulk overnight on one machine (downloads the 32.8 GB, one PDF at a time,
deleting each after measuring). The Library page then shows only books needing OCR by default.

- `amocr catalog inventory [--limit N] [--folder Texts] [--max-mb M] [--local]`: smallest
  PDFs first; resumable (saved after every PDF); skips PDFs anyone has already measured.
- Facts per PDF (keyed by SHA-1), shared like the board, one file per person in
  `<material folder>/catalog/inventory/`: pages, scanned pages, page kinds (Devanagari,
  IAST, Latin, legacy-font text, none), verdict (*needs OCR*, *has a text layer*,
  *partly usable text*, *not a PDF*), why (scanned pages, or the legacy font's name),
  and the script from Tesseract's script detection on three pages. No book text.
- **A text layer isn't trusted just for being in the right script.** Three checks:
  - *Born-digital or OCR?* Text lying over a full-page scan (or a PDF made by an OCR
    program) is someone's OCR. Word or Distiller documents that merely contain page images
    are born-digital.
  - *Garbled?* A text-only screen: Devanagari vowel signs or viramas with no consonant
    before them (real text: 0%; over 1% means fonts that don't map back to Unicode), and,
    on Latin pages, leftovers of legacy fonts (Ë Ý Æ µ …) beyond IAST, ISO 15919, European
    accents and other Indic scripts (Śāradā is real text).
  - *How good is an OCR layer?* Three of its pages are read afresh (Surya, else Tesseract)
    and the words compared, in any order: the share of the layer's words confirmed, the
    share of the page's words the layer has, and how many IAST diacritics survived. Good,
    fair or poor; anything but good counts as needing OCR.
- Found on the first 15 PDFs: placeholder files that aren't PDFs (macOS iCloud stubs,
  a web filter's "blocked download" page saved as .pdf), and texts typeset in the
  legacy Sanskrit99 font (Devanagari stored as Latin letters). Those could be converted
  by a font map instead of OCR.

### D. Assemble

`amocr assemble <book> [--commentary-layer hindi-mishra] [--chapter-at PAGE=CH] [--push]`:
page texts into units with IDs work/chapter/verse/layer, written as numbered builds
(`units/v001/`, never changed; an unchanged result makes no new build) and shared with the
book's folder.

- Each page's best text: the person's saved text, else Claude's, else Surya's.
- Lines are classed from the text, not from the engines' labels (which proved unreliable):
  running header, verse (ends in a daṇḍa, numbered ॥ ३४ ॥), commentary (Hindi words),
  footnote (१. … at the foot), colophon (इति … तन्त्रे …, and the Hindi … अधिकार परिपूर्ण).
- **Two streams.** A verse is complete at its number; a commentary passage at the number of
  the verse(s) it explains (॥ ३५-३६ ॥), which gives `explains`. Commentary runs on across
  pages while the next verses are printed above it.
- Chapters from the running header (ordinal + अधिकारः/पटलः/अध्यायः, also -तितम forms and
  OCR's dropped anusvāra); pages before chapter 1 and after the last colophon are left out.
- A unit is `validated` or `proofread` only if all its pages are; otherwise `draft`; `types: "guessed"`.
- `build.json` lists, per chapter, verse numbers missing or seen twice: the places for a
  proofreader to look (a misread number, or a line taken for the wrong layer).

First build of the pilot (from Surya, unproofread): 23 chapters, 1,317 verse units,
977 commentary passages, 461 footnotes; 15 verse numbers missing and 9 seen twice out of 1,280.

## Decisions

- Catalog lists **all 976 PDFs**; by default the Library shows those needing OCR (once
  Phase C knows which).
- Claims are **whole books** first.
- **Anyone** may release a claim that has been stale for 14 days; the release is recorded.
- Material folder: `[OCR Mirror]/Agama Mancha`; legible names; Vimarsha's internal use.

## Decided: releasing the team's books as editions

Agreed 2026-11-26. During proofreading a book lives in the library as **live assembled units**
(draft, proofread, validated); there is no export and re-import on every save. When a book (or a
chapter) is fully **validated**, the team **releases an edition**:

- **An export in TEI** (the format GRETIL uses) that keeps what makes the team's text richer than
  external e-texts: every passage's page, line and box on the scan (`pb`, `lb`, `facs`); verse numbers;
  each commentary as its own layer, linked to the verses it explains; footnotes and variant readings
  with their markers; per-passage status and who validated it; the exact printed copy (checksum).
- **A pinned version** like an imported external text: never edited, with version, date and checksum.
  Citations to "Mālinī, team edition v1" stay stable while corrections go on towards v2.
- **The team's output**: archived, shared with scholars, or contributed to GRETIL or Muktabodha if the
  rights allow (the modern commentary's copyright checked first).

| | During proofreading | Released |
|---|---|---|
| In the library | live units (draft / proofread / validated) | a pinned edition, versioned |
| Citations point to | the current build | the release (stable) |
| Format | units | TEI export, plus the same units |

The team's books are the master copies; external e-texts serve as references (the GRETIL
cross-check). To build: a *Release edition* step (validated build → TEI → pinned version), after
Mālinī's first chapters are validated.

## Proposed: a hosted version (design, not decided)

*Written 2026-11-25 from a discussion with the owner. Nothing here is built yet; the open
decisions at the end come first.*

### Goal

One Agama Mancha server that the team (and later a small circle of scholars) use from a
browser: the Library, Proofreading, the Librarian (works, search, read in context, study,
evaluation), each person with **their own Claude**. Not one server per person.

### Why today's setup doesn't carry over as it is

Today the app and a person's Claude Code session meet through files on the same machine (the
proofreading chat and the study chat: `amocr chat wait`, `librarian study wait`). A hosted
version replaces that bridge; it does not copy it per person.

### How each person's Claude is reached

A web page can't use someone's Claude **subscription** (Pro, Max): subscriptions work only in
Anthropic's own apps (claude.ai, Claude Desktop, Claude Code). Three routes, all answering under
the same librarian rules (they live in the tool's instructions and CLAUDE.md, not in a route):

| Route | Who writes the answer | Needs | In the app |
|---|---|---|---|
| **1. Listener** | the person's Claude Code on their own machine, connected to the server | their Pro/Max plan; Claude Code running while they study | ask in the panel, the answer appears there |
| **2. Own API key** | the server, calling Claude with the person's key | an API key, billed per use | ask in the panel, the answer appears there; nothing to install |
| **3. Connector** | the person's claude.ai / Claude Desktop, with the Agama Mancha connector added | their Pro/Max plan | they ask in Claude; the cited answer is saved to their study thread and shows in the panel |

Recommendation: routes 1 and 2 in the panel, route 3 for people who live in Claude. The server
never sees subscription credentials. For route 2, keys stay in the browser session and are never
stored.

### The listener needs no access to anyone's network

Every connection starts on the person's side, like a browser or Claude Code itself:

1. The person runs a listener in their Claude Code with a personal token from their account.
2. It asks the server over HTTPS for their pending questions (a long-held request) and reconnects.
3. A question asked in the panel goes to that person's waiting listener only.
4. Claude reads the passages (through the hosted librarian), answers, and the listener posts the
   answer back over HTTPS; the panel shows it.

Only outbound HTTPS from the person's machine; no inbound access, VPN or port forwarding; the
server needs only its public HTTPS port. A token sees only its owner's questions and can be
revoked.

### Architecture

| Part | Today | Hosted |
|---|---|---|
| Web app | `amocr serve` on 127.0.0.1, one person | the same pages behind accounts and HTTPS |
| Librarian | MCP over stdio for the local Claude Code | the same tools over HTTP (MCP streamable HTTP), per-user auth: for listeners and connectors |
| Library and index | `data/library/` (e-texts, units, LanceDB) on each machine | one copy on the server; imports and rebuilds there |
| Scans and page readings | each volunteer's `data/works/`, shared through Proton | on the server, synced from the material folder |
| Board, claims, proofreading saves, history, study chats, evaluation | files, merged through Proton | a small database with per-user records (the ladder, page grid and history carry over as they are) |
| Identity | the `operator` name in `data/config.toml` | accounts; the operator name becomes the account |

### Privacy, rights, access

- **Internal use stays the rule.** The scans and the printed books' text are for Vimarsha only:
  accounts by invitation, roles (proofreader, validator, coordinator, reader).
- **Restricted works** (design doc's access tier): readable and searchable on the server, but never
  sent to an external model by any route; the server enforces it, not the person's Claude.
- **Licences travel with each work** (GRETIL's CC BY-NC-SA: non-commercial, share-alike if shared).
  Opening the library to outside scholars is a sharing act: check each work's licence first.

### Security: members of Vimarsha only

Two layers, and no passwords of our own to store or leak.

**1. A gate in front of everything.** Nothing on the server (pages, API, scans, the MCP
endpoint) can be reached without first proving you are a listed member. Two good options:

| | Cloudflare Tunnel + Cloudflare Access | Tailscale |
|---|---|---|
| How it works | the VPS opens **no inbound ports**: a small `cloudflared` process connects out to Cloudflare, which lets a request through only after the person proves an allowed email (one-time code, or Google login) | the server isn't on the public internet at all; members join Vimarsha's private network (the "tailnet") by invitation and reach the app there |
| Who is a member | an allow-list of emails, or a Google group, kept by the coordinator | the tailnet's member list, kept by the coordinator |
| Members install | nothing (a browser) | the Tailscale app on each device |
| Listeners (Claude Code) | a per-person service token through Access | work as they are, inside the tailnet |
| claude.ai connector (route 3) | possible later, with the MCP endpoint's own sign-in (OAuth) | not possible: claude.ai's servers can't reach a private tailnet |
| Cost | free for small teams | free for small teams |

Recommendation: **Cloudflare Tunnel + Access** (nothing for members to install, no open ports,
room for the connector later); Tailscale if the team prefers a fully private network.

**2. Inside the app,** from the verified identity the gate passes on:

- **Roles:** reader, proofreader, validator, coordinator, admin. The coordinator invites and
  removes members; there is no sign-up page.
- **Personal tokens** for listeners and the MCP endpoint, each revocable from the person's account.
- **Restricted works** are enforced by the server: never sent to an external model by any route.
- **An audit log** of sign-ins, imports, claims and status changes; rate limits on the API.

**And the machine itself:** TLS everywhere, the disk encrypted, secrets only in environment
variables, automatic security updates, SSH by key only (or only through the tunnel), and the
server's backups encrypted.

### Deployment

**One VPS.** OCR (Surya, Claude review) stays on volunteers' Macs, where it runs today, and
results arrive as they do now; the server hosts, searches and coordinates, so it needs no GPU.

| | |
|---|---|
| Size to start | 4 vCPU, 16 GB RAM, ~200 GB disk: the original PDFs (~33 GB) and page images (~150 MB per book so far, so the whole library's scans grow to roughly 150–250 GB over time) |
| Containers (Docker Compose) | the app; Ollama with bge-m3 for search queries and imports (fine on CPU); `cloudflared` for the tunnel; the database; a backup job |
| Database | SQLite for a team this size (one file, continuously copied off the machine with Litestream); PostgreSQL if it grows |
| Web server | the app moves from Python's built-in server to a production one (an ASGI framework behind uvicorn) |
| Updates | a merge to `main` → GitHub Actions runs the tests and builds the image → the VPS pulls it and restarts (one command, or automatic); database changes as migrations |
| Backups | nightly, encrypted (restic) to a second place, e.g. Proton or object storage; a restore tested once a month |
| Watching it | an uptime check and the container logs; an alert to the coordinator if it goes down |
| Cost | roughly €15–40 a month for the VPS; Cloudflare and Tailscale free at this size |

**Getting the library onto it:** the e-texts and index are rebuilt there (`librarian ingest`,
`build`); books' page readings and proofreading come from the material folder, synced from Proton
(a member signs the Proton CLI in on the server once) or pushed by volunteers as today.

**Order of work:** (H1) the private server for the team: gate, accounts, database, the pages as
they are, route 1 listeners; OCR still pushed from volunteers' Macs as today; (H2) OCR workers, and
route 2 (per-person API keys); (H3) the connector for claude.ai and, if decided, access for scholars.

### Who can work from a browser alone

| Work | Browser only | Needs a Claude route (listener or own key) | Needs a worker (below) |
|---|---|---|---|
| Library: catalog, claims, board, inventory | yes | | |
| Proofreading: Proofread, ladder, page grid, history, Suggestions, structure warnings, GRETIL cross-check | yes | | |
| Validating another person's pages | yes | | |
| Librarian: works, search, read in context with scans, import e-texts, evaluation review | yes | | |
| Coordinating: members, stale claims, assembling a book | yes | | |
| Study with Claude, *Check with Claude*, the proofreading chat | | yes | |
| Claude reviewing pages | | yes (as a worker job) | |
| OCR of new books (Tesseract, Surya) | | | yes |

So readers, proofreaders, validators and coordinators do all their work in the browser from day
one; only producing new OCR needs a machine that can run the engines.

### OCR workers: members' own machines do the reading

The server has no GPU, and Surya is slow on an ordinary CPU. Instead of renting GPUs, members'
machines do the OCR, the same way the Claude Code listener answers questions: a **worker** on a
member's machine pulls work from the server over HTTPS, runs its own engines, and sends the
readings back. The server never connects to anyone's network.

1. **The member starts a worker** with their personal token (`amocr worker --server … --token …`).
   It reports what it can run, with exact versions: Tesseract with the pinned Sanskrit and Hindi
   models, Surya, a local vision model, Claude Code (for review).
2. **It asks for work:** a batch of pages of a book someone has claimed, for an engine it has.
3. **The server leases it a batch** (say 20 pages). If the worker disappears, the lease expires and
   the batch goes to another worker: no page lost, none done twice.
4. **The worker fetches the page images, runs the engine, uploads the readings**, each labelled
   with engine, version and worker, exactly like page readings today, then deletes its copies.
5. **The book's page grid fills in** as batches return from whoever has capacity.

**Engines:**

- **Tesseract and Surya:** the measured engines. Surya runs well on Apple Silicon and on PCs with a
  GPU; Tesseract anywhere.
- **Local vision models** (e.g. Qwen through Ollama): allowed only as an extra reading for
  comparison, never as the draft, until one proves itself on the evaluation (in our test Qwen broke
  39 of 118 correct lines and garbled Sanskrit; docs/engines.md).
- **Claude Code:** the "review" job, i.e. the listener as part of the same worker; never given
  restricted books.

**Why this way:** free, and it grows with the team (each member's Mac adds capacity); no Proton setup
needed by anyone; results comparable because engine and model versions are pinned and recorded;
scans go only to members' machines, over HTTPS, and aren't kept. The fallback, if members' machines
aren't enough, is a GPU machine rented by the hour that runs the same worker.

### Trial at home (being built, 2026-11-26)

`amocr serve --hosted` (members only: a sign-in page with name and password, scrypt-hashed and kept on
the server only; invite links to choose a password; 30-day sessions; lockout after five wrong tries;
listener tokens; refuses to listen beyond this machine without it), `amocr member add|invite|token|list|remove`,
per-member study threads, and the listener side (`librarian --server … study wait|reply`, `get`,
`search`; or `AGAMA_SERVER` / `AGAMA_TOKEN`). Windows as the server, the Mac as a member's machine:
docs/hosted-trial.md (PR #25). OCR workers built (2026-11-26): `amocr queue <book> --engine surya` on the
server, `amocr worker` on a member's machine (leases, 15-minute expiry, three tries, readings saved like
local ones and credited to the member); readers can't run workers. Volunteers are browser-only (decided 2026-11-26): no API key, so
each person's own Claude answers, through the **Claude helper**, a `.cmd` file made for them on their
Account page (server and a helper token inside) that installs and signs in to Claude Code on first run
and answers their panel questions inline; OCR runs on a managed pool of machines (the Mac for now).

### What changes in the code (when it's decided)

1. Accounts and roles from the gate's verified identity (no passwords of our own); the operator
   name from the login; personal tokens; an audit log.
2. A database for the board, claims, ladder, history, study and evaluation, replacing the files
   (and Proton as the coordination channel).
3. The librarian MCP server over HTTP with per-user tokens; the study queue as an HTTP API that
   listeners long-poll; `librarian study wait --server …` on the person's side.
4. Route 2: an optional per-person API key in the browser session; the server calls Claude with it.
5. Route 3: a connector tool that saves an answer to the person's study thread.
6. Sync of the library and the material folder to the server; backups.
7. A production web server (ASGI) in place of Python's built-in one; a container image built by CI.
8. The worker: a job queue with leases on the server; `amocr worker` (engines reported with versions,
   batches fetched and returned, Claude Code review as a job type, restricted books never to Claude).

### Open decisions

1. **Where it runs** (a VPS, a Vimarsha machine) and who administers it.
2. **The gate:** Cloudflare Access or Tailscale; and who keeps the member list.
3. **Who gets accounts** at first: the team only, or scholars too (and then, which works).
4. **Which Claude routes** to offer at launch (1 and 3 cost Vimarsha nothing; 2 bills each person).
5. **Proton's role**: remains the store of originals with the server syncing from it, or the
   server becomes the store and Proton the backup.
6. **When**: after Mālinī is finished end to end, or alongside it.
Decided (2026-11-26): **Claude listeners are personal**: a member's Claude answers only that
member's questions, never shared. **Local AI may be shared**: a member can run a worker with local
engines (Surya, Tesseract, local models) that serves everyone's jobs.

7. **Workers:** any member may run one, or only those the coordinator approves (readings are drafts
   until proofread and validated, so the risk is low; approval at first is the cautious start).
