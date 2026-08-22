#!/usr/bin/env bash
# Poll origin/main and deploy it when it has moved ahead of what this box is running.
#
#   ./scripts/auto-deploy.sh           # what cron runs, every quarter of an hour
#   ./scripts/auto-deploy.sh --force   # deploy a revision that already failed here
#
# Written for cron, not for people: use scripts/deploy.sh for an interactive deploy.
#
# It does three things a bare `git pull && deploy.sh` in a crontab would not. It refuses
# to touch a checkout that is dirty, detached, ahead of or diverged from origin/main —
# all of which mean someone is working on this box by hand. It puts the previously
# serving revision back when a deploy fails its smoke test, because the failure mode
# worth caring about is unattended: nobody is reading the log at 04:00. And it remembers
# the revision that failed, so the next tick does not rebuild the same broken commit
# every fifteen minutes until a human notices.
set -euo pipefail

# cron's environment is close to empty: git, docker and ssh all have to be findable, and
# the deploy key this repo fetches with lives in $HOME/.ssh/config.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME="${HOME:-/home/deploy}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BRANCH="${LAB_AUTO_DEPLOY_BRANCH:-main}"
STATE_DIR=.auto-deploy
LOG="$STATE_DIR/auto-deploy.log"
FAILED="$STATE_DIR/failed-revision"

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$STATE_DIR"

# cron appends to this log forever. Trim it here rather than asking for a logrotate
# config: the appends are O_APPEND, so shortening the file underneath them is safe.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 5000 ]; then
  tail -n 2000 "$LOG" > "$LOG.trim" && cat "$LOG.trim" > "$LOG" && rm -f "$LOG.trim"
fi

say() { echo "$(date -u +%FT%TZ) $*"; }

# A build takes minutes and the timer fires more often than that; two of these running
# at once would fight over the checkout and the containers.
exec 9>"$STATE_DIR/lock"
if ! flock -n 9; then
  say "another auto-deploy is still running; skipping this tick."
  exit 0
fi

git fetch --prune --quiet origin

CURRENT=$(git rev-parse HEAD)
TARGET=$(git rev-parse "origin/$BRANCH")

if [ "$CURRENT" = "$TARGET" ]; then
  say "up to date at ${TARGET:0:7}."
  exit 0
fi

# Everything below is a reason to leave the box alone and say so.
ON_BRANCH=$(git symbolic-ref --quiet --short HEAD || true)
if [ "$ON_BRANCH" != "$BRANCH" ]; then
  say "checkout is on '${ON_BRANCH:-a detached HEAD}', not $BRANCH; skipping."
  exit 0
fi

if [ -n "$(git status --porcelain)" ]; then
  say "working tree has local changes; skipping."
  exit 0
fi

if ! git merge-base --is-ancestor "$CURRENT" "$TARGET"; then
  say "local $BRANCH (${CURRENT:0:7}) is ahead of or diverged from origin/$BRANCH (${TARGET:0:7}); skipping."
  exit 0
fi

if [ "$FORCE" -eq 0 ] && [ -f "$FAILED" ] && [ "$(cat "$FAILED")" = "$TARGET" ]; then
  say "${TARGET:0:7} already failed to deploy here; waiting for a newer commit (or --force)."
  exit 0
fi

say "deploying ${CURRENT:0:7} -> ${TARGET:0:7}"
if ./scripts/deploy.sh; then
  rm -f "$FAILED"
  say "deployed $(git rev-parse --short HEAD)."
  exit 0
fi

# deploy.sh pulled, built and started the new revision before the smoke test told it the
# result was broken, so the lab is serving that revision right now. Put the old one back.
BROKEN=$(git rev-parse HEAD)
echo "$BROKEN" > "$FAILED"
say "deploy of ${BROKEN:0:7} failed its smoke test; rolling back to ${CURRENT:0:7}."
git reset --hard --quiet "$CURRENT"

if ./scripts/deploy.sh --no-pull; then
  say "rolled back to ${CURRENT:0:7}; ${BROKEN:0:7} will not be retried until a newer commit lands."
  exit 1
fi

say "ROLLBACK TO ${CURRENT:0:7} ALSO FAILED — the lab is down and needs a human."
exit 1
