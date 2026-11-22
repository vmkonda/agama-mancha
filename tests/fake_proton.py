"""Stand-in for the `proton-drive` CLI, backed by a local folder ($FAKE_PROTON_ROOT).

Implements only the calls amocr makes, with the same argument shapes as CLI 0.9.0.
"""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(os.environ["FAKE_PROTON_ROOT"])


def local(remote: str) -> Path:
    return ROOT / remote.strip("/")


def positional(args):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("--file-conflict-strategy", "--folder-conflict-strategy", "-f", "-d"):
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def main(argv):
    if argv[:1] == ["version"]:
        print("proton-drive 0.9.0 (fake)")
        return 0
    if argv[:1] != ["filesystem"]:
        print("unsupported", file=sys.stderr)
        return 2
    cmd, args = argv[1], positional(argv[2:])
    if cmd == "list":
        import json

        d = local(args[0])
        if not d.is_dir():
            return 1
        print(json.dumps([{"name": c.name} for c in sorted(d.iterdir())]))
        return 0
    if cmd == "info":
        return 0 if local(args[0]).exists() else 1
    if cmd == "create-folder":
        parent, name = local(args[0]), args[1]
        if not parent.is_dir():
            print(f"parent not found: {args[0]}", file=sys.stderr)
            return 1
        (parent / name).mkdir()
        return 0
    if cmd == "download":
        *remotes, dest = args
        for r in remotes:
            src = local(r)
            if not src.exists():
                print(f"not found: {r}", file=sys.stderr)
                return 1
            target = Path(dest) / src.name
            (shutil.copytree(src, target, dirs_exist_ok=True) if src.is_dir() else shutil.copy2(src, target))
        return 0
    if cmd == "upload":
        *sources, parent = args
        p = local(parent)
        if not p.is_dir():
            print(f"parent not found: {parent}", file=sys.stderr)
            return 1
        for s in sources:
            s = Path(s)
            (shutil.copytree(s, p / s.name, dirs_exist_ok=True) if s.is_dir() else shutil.copy2(s, p / s.name))
        return 0
    print(f"unsupported filesystem {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
