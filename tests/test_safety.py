"""Safety rails: amocr can't delete or write outside the results folder; the hook blocks Claude's workarounds."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_fake_proton

from amocr.proton import Proton, ProtonError, mirror_dir, results_root

HOOK = Path(__file__).resolve().parents[1] / ".claude/hooks/guard_proton.py"


@pytest.fixture
def pd(tmp_path, monkeypatch):
    root = tmp_path / "proton"
    (root / "shared-with-me/Team/Tantra").mkdir(parents=True)
    (root / "shared-with-me/OCR Mirror").mkdir(parents=True)
    fake = make_fake_proton(tmp_path)
    monkeypatch.setenv("FAKE_PROTON_ROOT", str(root))
    monkeypatch.setenv("AMOCR_DATA", str(tmp_path / "data"))
    return Proton(str(fake), write_root="/shared-with-me/OCR Mirror"), root


def test_destructive_operations_are_impossible(pd):
    p, _ = pd
    for op in (("filesystem", "delete", "/x"), ("filesystem", "trash", "/x"), ("filesystem", "empty-trash"),
               ("filesystem", "move", "/a", "/b"), ("sharing", "invite", "/x"), ("auth", "logout")):
        with pytest.raises(ProtonError, match="never runs"):
            p._run(*op)


def test_writes_only_inside_results_folder(pd, tmp_path):
    p, root = pd
    f = tmp_path / "x.txt"
    f.write_text("x")
    for target in ("/shared-with-me/Team", "/shared-with-me/Team/Tantra", "/shared-with-me/OCR Mirror2",
                   "/shared-with-me/OCR Mirror/../Team", "/my-files"):
        with pytest.raises(ProtonError, match="refusing"):
            p.upload(f, target)
        with pytest.raises(ProtonError, match="refusing"):
            p.mkdir_p(target + "/new")
    p.mkdir_p("/shared-with-me/OCR Mirror/Tantra/Book.amocr")
    p.upload(f, "/shared-with-me/OCR Mirror/Tantra")
    assert (root / "shared-with-me/OCR Mirror/Tantra/x.txt").exists()
    assert not (root / "shared-with-me/Team/x.txt").exists()
    log = (tmp_path / "data/proton.log").read_text()
    assert "upload" in log and "create-folder" in log


def test_results_root_must_exist(pd, tmp_path):
    p, root = pd
    (root / "shared-with-me/OCR Mirror").rmdir()
    with pytest.raises(ProtonError, match="doesn't exist"):
        p.mkdir_p("/shared-with-me/OCR Mirror/Tantra")


def test_separate_results_share():
    assert results_root("/shared-with-me/Team", "/shared-with-me/OCR Mirror") == "/shared-with-me/OCR Mirror"
    assert mirror_dir("/shared-with-me/Team/T/B.pdf", "/shared-with-me/Team", "/shared-with-me/OCR Mirror") \
        == "/shared-with-me/OCR Mirror/T/B.amocr"


def hook(event, env=None):
    import os

    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    return r.returncode


@pytest.mark.parametrize("cmd", [
    "proton-drive filesystem delete '/shared-with-me/Team/book.pdf'",
    "~/bin/proton-drive filesystem trash /shared-with-me/Team",
    "proton-drive filesystem list /shared-with-me && proton-drive filesystem empty-trash",
    "proton-drive sharing remove-url /shared-with-me/Team",
    "proton-drive filesystem upload x /shared-with-me/Team",
    "proton-drive",
    "python -c \"import subprocess; subprocess.run(['proton-drive','filesystem','delete','/x'])\"",
    "C:\\Tools\\proton-drive.exe filesystem move /a /b",
])
def test_hook_blocks(cmd):
    assert hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) == 2


@pytest.mark.parametrize("cmd", [
    "proton-drive filesystem list /shared-with-me",
    "~/bin/proton-drive version",
    "proton-drive invitation list",
    "uv run amocr push B-123",
    "uv run amocr doctor",
    "git status",
])
def test_hook_allows(cmd):
    assert hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) == 0


def test_hook_protects_safety_code():
    ev = {"tool_name": "Edit", "tool_input": {"file_path": "/x/agama-mancha/src/amocr/proton.py"}}
    assert hook(ev) == 2
    assert hook(ev, {"AMOCR_DEV": "1"}) == 0
    assert hook({"tool_name": "Write", "tool_input": {"file_path": "/x/agama-mancha/src/amocr/cli.py"}}) == 0


def test_hook_blocks_scripts_that_would_delete():
    ev = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.sh", "content": "proton-drive filesystem delete /a"}}
    assert hook(ev) == 2
    ok = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/notes.md", "content": "never run proton-drive delete"}}
    assert hook(ok) == 0


def test_session_cookie_is_secure_behind_https():
    from amocr.server import Handler

    h = Handler.__new__(Handler)
    h.headers = {"X-Forwarded-Proto": "https"}
    assert "; Secure" in h._session_cookie("abc") and "; Secure" in h._session_cookie(None)
    h.headers = {}
    assert "Secure" not in h._session_cookie("abc")  # plain HTTP at home: a Secure cookie would never come back
