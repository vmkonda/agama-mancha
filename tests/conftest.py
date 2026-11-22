import os
import sys
from pathlib import Path

FAKE = Path(__file__).with_name("fake_proton.py")


def make_fake_proton(folder: Path) -> Path:
    """An executable stand-in for proton-drive that works on macOS, Linux and Windows."""
    if os.name == "nt":
        exe = folder / "proton-drive.cmd"
        exe.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n', encoding="utf-8")
    else:
        exe = folder / "proton-drive"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return exe
