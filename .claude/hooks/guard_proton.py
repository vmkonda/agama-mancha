"""Claude Code PreToolUse hook: keep Claude sessions from changing Proton Drive directly.

Claude reaches Proton Drive only through `amocr`, whose wrapper (src/amocr/proton.py)
can read, create folders and upload inside the results folder, nothing else.
This hook blocks the ways around that:

- running proton-drive itself for anything except read-only commands
  (version, filesystem list/info, invitation list);
- any shell command that mentions a destructive Proton operation
  (delete, trash, empty-trash, move, rename, restore, sharing, auth logout, takeout);
- editing the safety code (proton.py, this hook, the hook settings)
  unless the developer sets AMOCR_DEV=1 before starting Claude.

Exit code 2 blocks the tool call and shows the reason to Claude.
"""

import json
import os
import re
import sys

READ_ONLY = re.compile(
    r"proton-drive(\.exe)?\s+("
    r"version|--version|-v|help|--help|-h"
    r"|filesystem\s+(list|info)"
    r"|invitation\s+list"
    r"|auth\s+login"
    r")\b"
)
MENTIONS_PROTON = re.compile(r"proton-drive|proton_drive|ProtonDriveApps", re.I)
DESTRUCTIVE = re.compile(
    r"\b(delete|trash|empty-trash|move|rename|restore|sharing|set-url|remove-url|leave|logout|takeout|"
    r"create-folder|upload)\b"
)
PROTECTED_FILES = ("src/amocr/proton.py", ".claude/hooks/guard_proton.py", ".claude/settings.json")


def block(reason: str) -> None:
    print(f"Blocked by the Proton Drive guard: {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool = event.get("tool_name", "")
    inp = event.get("tool_input") or {}

    if tool == "Bash":
        cmd = inp.get("command", "")
        if MENTIONS_PROTON.search(cmd):
            # Every proton-drive invocation in the command must be read-only.
            calls = re.findall(r"proton-drive(?:\.exe)?[^;&|\n]*", cmd)
            if not calls or any(not READ_ONLY.match(c) for c in calls):
                block(
                    "Claude may only run read-only proton-drive commands (version, filesystem list/info, "
                    "invitation list). Use `uv run amocr push|pull|fetch` for everything else; it only writes "
                    "inside the results folder and never deletes."
                )
            if DESTRUCTIVE.search(cmd):
                block("this command mentions a Proton Drive write or delete operation.")
        return

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = (inp.get("file_path") or inp.get("notebook_path") or "").replace("\\", "/")
        if any(path.endswith(p) for p in PROTECTED_FILES) and os.environ.get("AMOCR_DEV") != "1":
            block(
                f"{path} holds the Proton Drive safety rules. A developer can change it by starting "
                "Claude with AMOCR_DEV=1, after review."
            )
        # A script written now and run later must not smuggle in Proton writes or deletes.
        text = " ".join(str(inp.get(k, "")) for k in ("content", "new_string", "new_source"))
        text += " ".join(str(e.get("new_string", "")) for e in inp.get("edits") or [] if isinstance(e, dict))
        if MENTIONS_PROTON.search(text) and DESTRUCTIVE.search(text) and os.environ.get("AMOCR_DEV") != "1":
            if not any(path.endswith(s) for s in (".md", ".txt")):
                block("this file would contain code that writes to or deletes from Proton Drive.")


if __name__ == "__main__":
    main()
