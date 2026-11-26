#!/usr/bin/env bash
# Bring the VPS up to date with the deploy branch and restart Agama Mancha.
# Run by GitHub Actions over SSH (.github/workflows/deploy.yml), or by hand on the server:
#   scripts/linux/deploy.sh
# data/ (library, index, members, proofreading) is not in git and is never touched.
# Local edits to the code make it stop rather than overwrite them.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"                 # uv, for a non-interactive SSH session
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"   # systemctl --user, from a forced-command key
BRANCH="${AMOCR_DEPLOY_BRANCH:-deploy}"
SERVICE="${AMOCR_SERVICE:-agama-mancha}"
PORT="${AMOCR_PORT:-8770}"
cd "$(dirname "$0")/../.."
say() { echo "$(date -u +%Y-%m-%dT%H:%MZ)  $*"; }

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "local changes to the code; not updating:"; git status --short; exit 1
fi
git fetch --quiet origin "$BRANCH"
before=$(git rev-parse HEAD)
target=$(git rev-parse "origin/$BRANCH")
# reset, not merge: a force-push of an older commit to the deploy branch is how to roll back.
git checkout --quiet -B "$BRANCH" "origin/$BRANCH"
git reset --quiet --hard "$target"
[ "$before" = "$target" ] || git log --oneline "$before..$target" 2>/dev/null | head -20 || true
uv sync --quiet --extra librarian
systemctl --user restart "$SERVICE"

# Wait until it answers with the new code (the first start after an update can take a while).
code=""
for _ in $(seq 1 60); do
  code=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/api/version" 2>/dev/null | sed -n 's/.*"code": *"\([0-9a-f]*\)".*/\1/p' || true)
  [ "$code" = "$target" ] && break
  sleep 2
done
if [ "$code" != "$target" ]; then
  say "the server isn't answering with ${target:0:7} (it says '${code:0:7}'). Its last log lines:"
  journalctl --user -u "$SERVICE" -n 30 --no-pager 2>/dev/null || true
  exit 1
fi
say "running ${target:0:7} (was ${before:0:7})"
