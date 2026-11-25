---
name: ocr-view
description: Show a page's original scan and its OCR output side by side in a browser, compare engines or an engine against ground truth, edit ground truth, and answer the viewer's chat panel. Use when the user asks to see, view, compare, review, check or correct an OCR page (e.g. "show me page 231", "compare Claude and Tesseract on p51"), or says "listen to the viewer chat".
---

# ocr-view

The viewer is `amocr serve`, a local web app bound to 127.0.0.1:8791 on this Mac.
It is never published or exposed on the network: the scans are copyrighted.

## Steps

1. Make sure the page has output. If `data/works/<work>/pages/NNNN/ocr/` is empty, run
   `uv run amocr ocr <work> --pages N` first.
2. Check whether the viewer is already running: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8791/`.
   If not, start it in the background: `uv run amocr serve --no-browser --open <work>/<N>`
   (run_in_background). Do not stop it at the end of the turn; the user is using it.
3. Tell the user the URL `http://localhost:8791/#<work>/<N>`.
   The user usually works on this Mac over SSH from another machine, so also give the
   tunnel command, to run on their own machine:
   `ssh -N -L 8791:127.0.0.1:8791 <the host they ssh to>`
   or, inside an open ssh session: Enter, `~C`, then `-L 8791:127.0.0.1:8791`.
   Never suggest binding to 0.0.0.0 instead.

## What the viewer does

- **View**: scan on the left, chosen output on the right. Tesseract lines below
  confidence 70 are highlighted; hovering a line outlines it on the scan. Claude
  results show labelled regions (header, verse, commentary, footnote), its change
  list and its uncertain readings.
- **Compare**: character diff between any two outputs, with CER.
- **Proofread**: edit and save to `data/works/<book>/groundtruth/pNNNN.txt`, with the
  reviewer's name, a note, and a "verified" tick that should be set only once every
  line has been checked against the print.
- **Suggestions**: fixes learned from corrections, offered across the book (see CLAUDE.md).
- **Chat**: a panel where the proofreader talks to this Claude session. See below.

## "Listen to the viewer chat"

The viewer can't call Claude; you answer from this session.

0. If the book has a brief (`data/works/<book>/brief.md`; `chat wait` prints its path), read it
   once at the start: what the text is, its layout, conventions and the engine's habits.
1. Run `uv run amocr chat <book> wait` with run_in_background. While it waits, the
   viewer shows "Claude is listening". It exits when the person sends a message,
   printing the message, the line it is about (as it stands now) and that line's image.
2. When it exits, read the line image if there is one, then answer with
   `uv run amocr chat <book> reply <id> --text "..."`. Add `--fix PAGE:LINE:"whole new line"`
   to propose a change, or `--rule <id>` after adding a rule with `amocr rule add`.
   The person applies proposals in the viewer; never edit page text yourself.
   **CHECK REQUEST** messages come from the "Check with Claude" button: `wait` prints every
   line in the range and one image covering them. Compare each line with the image and reply
   in one message: say which lines match, and add a `--fix PAGE:LINE:"whole line as printed"`
   for each line that differs (misprints stay as printed; say what you're unsure of).
3. Start `chat wait` again straight away, and keep doing so until the person says to
   stop. If it times out (exit code 3), start it again too.

Each answer uses the person's plan: keep answers short and look only at the lines asked about.
