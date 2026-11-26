#!/usr/bin/env bash
# Bring the VPS up to date with main and restart Agama Mancha.
# Run by GitHub Actions over SSH (.github/workflows/deploy.yml) after every merge to main, or by hand:
#   scripts/linux/deploy.sh                # the latest main
#   scripts/linux/deploy.sh deploy <commit> # an earlier commit of main (to roll back)
# Over SSH the key is a forced command: what the workflow sent arrives in SSH_ORIGINAL_COMMAND and
# is only read as "deploy [commit]", the commit checked to be hex and on main. Nothing else runs.
# data/ (library, index, members, proofreading) is not in git and is never touched.
# Local edits to the code make it stop rather than overwrite them.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"                 # uv, for a non-interactive SSH session
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"   # systemctl --user, from a forced-command key
BRANCH="${AMOCR_DEPLOY_BRANCH:-main}"
SERVICE="${AMOCR_SERVICE:-agama-mancha}"
PORT="${AMOCR_PORT:-8770}"
cd "$(dirname "$0")/../.."
say() { echo "$(date -u +%Y-%m-%dT%H:%MZ)  $*"; }

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "local changes to the code; not updating:"; git status --short; exit 1
fi
request="${SSH_ORIGINAL_COMMAND:-$*}"
want=""
if [[ "$request" =~ ^deploy[[:space:]]+([0-9a-f]{7,40})$ ]]; then
  want="${BASH_REMATCH[1]}"
elif [[ -n "$request" && ! "$request" =~ ^deploy$ ]]; then
  say "unknown request; only 'deploy' or 'deploy <commit>'"; exit 2
fi
git fetch --quiet origin "$BRANCH"
before=$(git rev-parse HEAD)
target=$(git rev-parse "origin/$BRANCH")
if [ -n "$want" ]; then                     # roll back (or forward) to a commit that is on main
  target=$(git rev-parse --verify --quiet "$want^{commit}") || { say "no commit $want here"; exit 2; }
  git merge-base --is-ancestor "$target" "origin/$BRANCH" || { say "$want isn't on $BRANCH; refusing"; exit 2; }
fi
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
