"""Two volunteers sharing one book through a (fake) Proton Drive."""

import json
import os
import stat
import sys
from pathlib import Path

import pymupdf
import pytest
from conftest import make_fake_proton

from amocr import config as cfgmod
from amocr.cli import main
from amocr.proton import mirror_dir

TEAM = "/shared-with-me/Team"


@pytest.fixture
def drive(tmp_path, monkeypatch):
    root = tmp_path / "proton"
    (root / "shared-with-me/Team/Tantra").mkdir(parents=True)
    (root / "shared-with-me/Team/OCR Mirror").mkdir()  # the coordinator creates it; amocr never does
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(root / "shared-with-me/Team/Tantra/Test Book.pdf")
    fake = make_fake_proton(tmp_path)
    monkeypatch.setenv("FAKE_PROTON_ROOT", str(root))
    return root, fake


def volunteer(tmp_path, monkeypatch, name, fake):
    monkeypatch.setenv("AMOCR_DATA", str(tmp_path / name))
    main(["init", "--operator", name, "--proton-root", TEAM + "/", "--proton-bin", str(fake), "--material", "OCR Mirror"])


def test_mirror_dir():
    assert mirror_dir(f"{TEAM}/Tantra/MVT.pdf", TEAM, "OCR Mirror") == f"{TEAM}/OCR Mirror/Tantra/MVT.amocr"
    assert mirror_dir(f"{TEAM}/MVT.pdf", TEAM + "/", "OCR Mirror") == f"{TEAM}/OCR Mirror/MVT.amocr"
    with pytest.raises(ValueError):
        mirror_dir("/my-files/other/MVT.pdf", TEAM, "OCR Mirror")


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    cfgmod.save(cfgmod.Config(operator='Ā "q"', proton_root="/shared-with-me/T"))
    assert cfgmod.load().operator == 'Ā "q"'


def test_two_volunteers_share_a_book(tmp_path, monkeypatch, drive, capsys):
    root, fake = drive
    from amocr.catalog import load_works

    # Volunteer A fetches the book, "finishes" page 2 with Claude and proofreads it, then pushes.
    volunteer(tmp_path, monkeypatch, "Anna", fake)
    main(["fetch", f"{TEAM}/Tantra/Test Book.pdf"])
    (wid,) = [w for w in load_works() if w.startswith("B-")]
    work = load_works()[wid]
    assert work.remote == f"{TEAM}/Tantra/Test Book.pdf" and work.source.exists()
    ocr = work.page_dir(2) / "ocr"
    ocr.mkdir(parents=True)
    (ocr / "claude-code-correct-m.json").write_text(json.dumps({"text": "पृष्ठ २\n", "operator": "Anna"}), encoding="utf-8")
    (ocr / "claude-code-correct-m.txt").write_text("पृष्ठ २\n", encoding="utf-8")
    work.gt_dir.mkdir(parents=True)
    (work.gt_dir / "p0002.txt").write_text("पृष्ठ २ (शुद्ध)\n", encoding="utf-8")
    (work.gt_dir / "p0002.meta.json").write_text(json.dumps({"reviewer": "Anna", "verified": True}), encoding="utf-8")
    main(["push", wid])

    shared = root / "shared-with-me/Team/OCR Mirror/Tantra/Test Book.amocr"
    meta = json.loads((shared / "book.json").read_text(encoding="utf-8"))
    assert meta["pages_total"] == 3 and meta["pages_done"]["claude"] == 1 and meta["updated_by"] == "Anna"
    assert meta["pages"]["2"]["review"]["verified"] is True
    assert (shared / "pages/p0002/claude-code-correct-m.json").exists()
    book_txt = (shared / "book.txt").read_text(encoding="utf-8")
    assert "पृष्ठ २ (शुद्ध)" in book_txt and "=== page 1 (none) ===" in book_txt

    # Volunteer B fetches the same book on another machine and gets A's work.
    volunteer(tmp_path, monkeypatch, "Bala", fake)
    capsys.readouterr()
    main(["fetch", f"{TEAM}/Tantra/Test Book.pdf"])
    assert "'results': 1" in capsys.readouterr().out
    work_b = load_works()[wid]  # same id: it comes from the PDF's checksum
    assert (work_b.page_dir(2) / "ocr/claude-code-correct-m.json").exists()
    assert (work_b.gt_dir / "p0002.txt").read_text(encoding="utf-8") == "पृष्ठ २ (शुद्ध)\n"

    # B's push merges into the same folder without losing A's files.
    main(["push", wid])
    assert (shared / "pages/p0002/claude-code-correct-m.json").exists()
    assert json.loads((shared / "book.json").read_text(encoding="utf-8"))["updated_by"] == "Bala"


def test_restricted_book_never_goes_to_claude(tmp_path, monkeypatch, drive):
    root, fake = drive
    volunteer(tmp_path, monkeypatch, "Anna", fake)
    main(["fetch", f"{TEAM}/Tantra/Test Book.pdf", "--restricted"])
    from amocr.catalog import load_works

    (wid,) = [w for w in load_works() if w.startswith("B-")]
    with pytest.raises(SystemExit, match="restricted"):
        main(["claude-next", wid])


def test_push_needs_operator_and_team_folder(tmp_path, monkeypatch, drive):
    root, fake = drive
    monkeypatch.setenv("AMOCR_DATA", str(tmp_path / "x"))
    with pytest.raises(SystemExit, match="team folder"):
        main(["fetch", f"{TEAM}/Tantra/Test Book.pdf"])
    main(["init", "--proton-root", TEAM, "--proton-bin", str(fake), "--material", "OCR Mirror"])
    with pytest.raises(SystemExit, match="outside|not inside"):
        main(["fetch", "/my-files/elsewhere.pdf"])


def test_folders_lists_shares(tmp_path, monkeypatch, drive, capsys):
    root, fake = drive
    volunteer(tmp_path, monkeypatch, "Anna", fake)
    capsys.readouterr()
    main(["folders"])
    assert "Team" in capsys.readouterr().out


def _catalog_with_test_book(root):
    import hashlib

    from amocr import library

    pdf = root / "shared-with-me/Team/Tantra/Test Book.pdf"
    e = {"path": "Tantra/Test Book.pdf", "name": "Test Book.pdf", "folder": "Tantra", "size": pdf.stat().st_size,
         "modified": "", "sha1": hashlib.sha1(pdf.read_bytes()).hexdigest(), "added_by": None}
    entries, _ = library.merge([], [e], "t0")
    library.save({"root": TEAM, "refreshed_at": "2026-11-25T00:00:00+00:00", "count": 1, "entries": entries})
    return e["sha1"]


def test_claims_on_the_board(tmp_path, monkeypatch, drive, capsys):
    from datetime import datetime, timedelta, timezone

    from amocr import board

    root, fake = drive
    volunteer(tmp_path, monkeypatch, "Anna", fake)
    key = _catalog_with_test_book(root)
    assert board.claim("Test Book")["ok"]
    assert (root / "shared-with-me/Team/OCR Mirror/catalog/board/Anna.json").exists()
    main(["fetch", f"{TEAM}/Tantra/Test Book.pdf"])
    b = board.refresh_board()[key]
    assert b["holder"] == "Anna" and b["stage"] == "inventoried" and b["progress"]["pages"] == 3

    volunteer(tmp_path, monkeypatch, "Bala", fake)
    _catalog_with_test_book(root)
    r = board.claim("Tantra/Test Book.pdf")
    assert not r["ok"] and "Anna" in r["why"]
    assert not board.release("Test Book")["ok"]  # not stale: only Anna may release it

    # Three weeks later, Anna's claim is stale: Bala may release it (recorded in Bala's file), then claim it.
    later = datetime.now(timezone.utc) + timedelta(days=21)
    monkeypatch.setattr(board, "_age_days", lambda at, now=None: (later - datetime.fromisoformat(at)).total_seconds() / 86400)
    r = board.release("Test Book")
    assert r["ok"] and r["released"] == "Anna"
    assert board.claim("Test Book")["ok"]
    b = board.merge(board.load_all())[key]
    assert b["holder"] == "Bala" and b["stage"] == "inventoried" and b["by"] == "Anna"  # Anna's progress still counts

    # The Library page gets it per catalog entry; Bala's copy fetches the PDF in the background.
    import time

    from amocr import server
    from amocr.catalog import load_works

    server.Handler.works = load_works()
    lib = server._library(server.Handler.works)
    assert lib["me"] == "Bala" and lib["entries"][0]["board"]["holder"] == "Bala"
    assert "book" not in lib["entries"][0]  # not on Bala's machine yet
    assert board.release("Test Book")["ok"]
    server._start_job("claim", key, server.Handler)
    while server._job["running"]:
        time.sleep(0.05)
    assert server._job["error"] is None and server._job["result"]["ok"] and server._job["result"]["fetched"]
    lib = server._library(server.Handler.works)
    assert lib["entries"][0]["book"] and lib["entries"][0]["board"]["holder"] == "Bala"


def test_board_merge_earliest_claim_wins():
    from amocr import board

    files = {
        "A": {"operator": "A", "books": {"k": {"claimed": True, "since": "2026-11-02T00:00:00+00:00"}}, "releases": []},
        "B": {"operator": "B", "books": {"k": {"claimed": True, "since": "2026-11-01T00:00:00+00:00",
                                               "stage": "read", "progress": {"pages": 2, "read": 2}}}, "releases": []},
    }
    assert board.merge(files)["k"]["holder"] == "B"
    files["A"]["releases"] = [{"key": "k", "holder": "B", "since": "2026-11-01T00:00:00+00:00"}]
    m = board.merge(files)["k"]
    assert m["holder"] == "A" and m["stage"] == "read"
    assert board.stage_of({"pages": 2, "read": 2, "claude": 0, "proofread": 1, "verified": 0}) == "proofreading"
    assert "/" not in board.file_name("Ā b/../c") and board.file_name("vmkonda") == "vmkonda.json"
