"""Setup helpers so a volunteer (or their Claude session) needs no admin rights or manual downloads.

- get_proton_cli: the official Proton Drive CLI for this OS/CPU into data/bin/
- get_models: Tesseract's Sanskrit/Hindi models into data/tessdata/, pinned and
  checksum-verified, identical on every platform (the same tessdata_fast files
  Homebrew's tesseract-lang installs, which the pilot was measured with)
"""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import urllib.request
from pathlib import Path

from .catalog import data_dir
from .proton import TESTED_VERSION

# tesseract-ocr/tessdata_fast at a fixed commit; values are git blob ids (sha1 of "blob <size>\0" + data).
MODELS_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODELS = {
    "san": "3df043f3247fd41a21ac47c3b199bc87643e984b",
    "hin": "a8f0aaec09378115b12a2c6287c57695d082aea2",
    "eng": "bbef4675053b5b468cdb477053e28b1c698ba08e",
    "osd": "527457ca8f8fe1fda7c2f88bce3c0e4be12be9d0",
}
MODELS_LABEL = f"tessdata_fast@{MODELS_COMMIT[:7]}"


def tessdata_dir() -> Path:
    return data_dir() / "tessdata"


def proton_cli_path() -> Path:
    return data_dir() / "bin" / ("proton-drive.exe" if os.name == "nt" else "proton-drive")


def _platform_tag() -> str:
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = platform.machine().lower()
    cpu = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("x86_64", "amd64") else None
    if not system or not cpu:
        raise SystemExit(f"no Proton Drive CLI build for {platform.system()} {platform.machine()}; "
                         "see https://proton.me/download/drive/cli/index.html")
    return f"{system}-{cpu}"


def _download(url: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "agama-mancha-setup"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return data


def get_proton_cli(version: str = TESTED_VERSION) -> tuple[Path, str]:
    tag = _platform_tag()
    name = "proton-drive.exe" if tag.startswith("windows") else "proton-drive"
    url = f"https://proton.me/download/drive/cli/{version}/{tag}/{name}"
    dest = proton_cli_path()
    data = _download(url, dest)
    if len(data) < 1_000_000:
        dest.unlink(missing_ok=True)
        raise SystemExit(f"download from {url} looks wrong ({len(data)} bytes)")
    if os.name != "nt":
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest, hashlib.sha256(data).hexdigest()


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def models_present(langs: list[str]) -> bool:
    d = tessdata_dir()
    return all((d / f"{lang}.traineddata").exists() for lang in langs)


def get_models(langs: list[str] | None = None) -> list[str]:
    langs = langs or list(MODELS)
    got = []
    for lang in langs:
        if lang not in MODELS:
            raise SystemExit(f"no pinned model for {lang!r}; known: {', '.join(MODELS)}")
        dest = tessdata_dir() / f"{lang}.traineddata"
        if dest.exists() and _git_blob_id(dest.read_bytes()) == MODELS[lang]:
            continue
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{MODELS_COMMIT}/{lang}.traineddata"
        data = _download(url, dest)
        if _git_blob_id(data) != MODELS[lang]:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{lang}.traineddata failed its checksum; not installed")
        got.append(lang)
    return got
