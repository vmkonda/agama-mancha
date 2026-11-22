"""The only way amocr touches Proton Drive: a narrow, logged wrapper around the official CLI.

Safety rules enforced here (not just documented):
- Only read operations (version, info, list, download) and two write operations
  (create-folder, upload) can run. Delete, trash, empty-trash, move, rename,
  restore and every sharing command are impossible through amocr.
- Writes are allowed only at or below the results root (OCR Mirror). The
  originals are never written to.
- The results root must already exist; amocr never creates folders above it.
- Uploads keep history: an existing file gets a new revision, it is never
  trashed and replaced.
- Every call is appended to data/proton.log.

Tested against CLI 0.9.0. Public share links (drive.proton.me/urls/...) are not
usable by the CLI; folders must be shared with the volunteer's Proton account.
"""

from __future__ import annotations

import posixpath
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .catalog import data_dir

TESTED_VERSION = "0.9.0"

READ_OPS = {("version",), ("filesystem", "info"), ("filesystem", "list"), ("filesystem", "download")}
WRITE_OPS = {("filesystem", "create-folder"), ("filesystem", "upload")}


class ProtonError(RuntimeError):
    pass


def _norm(remote: str) -> str:
    p = posixpath.normpath("/" + remote.strip("/"))
    if ".." in p.split("/"):
        raise ProtonError(f"refusing path with '..': {remote!r}")
    return p


def _inside(path: str, root: str) -> bool:
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root + "/")


class Proton:
    def __init__(self, binary: str = "proton-drive", write_root: str | None = None):
        found = shutil.which(binary)
        if not found:
            raise ProtonError(
                f"Proton Drive CLI not found ({binary!r}). Download it from "
                "https://proton.me/download/drive/cli/index.html and run `amocr init --proton-bin <path>`."
            )
        self.bin = found
        self.write_root = _norm(write_root) if write_root else None

    def _log(self, args: tuple[str, ...], code: int) -> None:
        try:
            log = data_dir() / "proton.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\texit={code}\t{' '.join(args)}\n")
        except OSError:
            pass

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        op = tuple(args[:2]) if args[0] == "filesystem" else tuple(args[:1])
        if op not in READ_OPS | WRITE_OPS:
            raise ProtonError(f"amocr never runs `proton-drive {' '.join(op)}`")
        r = subprocess.run([self.bin, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self._log(args, r.returncode)
        if check and r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise ProtonError(f"proton-drive {' '.join(op)} failed: {msg[-1] if msg else r.returncode}")
        return r

    def _check_write(self, remote: str) -> str:
        if not self.write_root:
            raise ProtonError("no results folder configured; refusing to write")
        if not _inside(remote, self.write_root):
            raise ProtonError(f"refusing to write to {remote!r}: only {self.write_root!r} and below is writable")
        return _norm(remote)

    def version(self) -> str:
        return self._run("version").stdout.strip()

    def exists(self, remote: str) -> bool:
        return self._run("filesystem", "info", _norm(remote), "--json", check=False).returncode == 0

    def mkdir_p(self, remote: str) -> None:
        """Create missing folders between the results root (which must exist) and remote."""
        remote = self._check_write(remote)
        if not self.exists(self.write_root):
            raise ProtonError(f"results folder {self.write_root!r} doesn't exist or isn't shared with you; "
                              "ask the coordinator (amocr never creates it)")
        cur = self.write_root
        for name in [p for p in remote[len(self.write_root):].split("/") if p]:
            nxt = posixpath.join(cur, name)
            if not self.exists(nxt):
                self._run("filesystem", "create-folder", cur, name)
            cur = nxt

    def download(self, remote: str, local_dir: Path) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        # "remove" applies to the local temp folder only; the remote is never changed by a download.
        self._run("filesystem", "download", _norm(remote), str(local_dir),
                  "--file-conflict-strategy", "remove", "--folder-conflict-strategy", "merge")

    def upload(self, local: Path, remote_parent: str) -> None:
        """Upload into remote_parent. Existing files get a new revision (history kept); identical files are skipped."""
        parent = self._check_write(remote_parent)
        self._run("filesystem", "upload", str(local), parent,
                  "--file-conflict-strategy", "create-new-revision", "--folder-conflict-strategy", "merge",
                  "--skip-thumbnails")


def results_root(root: str, mirror: str) -> str:
    """mirror is either a full path (its own share, recommended) or a folder name inside root."""
    return _norm(mirror) if mirror.startswith("/") else _norm(posixpath.join(root, mirror))


def mirror_dir(remote_pdf: str, root: str, mirror: str) -> str:
    """'/R/Tantra/MVT.pdf' -> '<results root>/Tantra/MVT.amocr' (same tree as the originals)."""
    root = _norm(root) if root else ""
    if not root or not _inside(remote_pdf, root) or _norm(remote_pdf) == root:
        raise ValueError(f"{remote_pdf!r} is not inside the team folder {root!r}; check `amocr init --proton-root`")
    rel = _norm(remote_pdf)[len(root) + 1 :]
    parent, name = posixpath.split(rel)
    return posixpath.join(results_root(root, mirror), parent, posixpath.splitext(name)[0] + ".amocr")
