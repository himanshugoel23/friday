#!/usr/bin/env bash
# Deploy the latest code: pull -> build -> backup -> migrate -> restart one service at a time
# -> smoke test -> automatic rollback to the previous image if the smoke test fails.
#
#   sudo /opt/friday/deploy/update.sh              # normal release (waits for calls to finish)
#   sudo /opt/friday/deploy/update.sh --no-pull    # rebuild the code already on disk
#   sudo /opt/friday/deploy/update.sh --fast       # do not wait for live calls (calls in progress are cut)
#   sudo /opt/friday/deploy/update.sh --skip-backup
#   sudo /opt/friday/deploy/update.sh --rollback   # go back to the previous image NOW
#
# Images are tagged with the git commit: friday:<sha>. The last two are kept for rollback.
# Database changes are NOT undone by a rollback (migrations are additive); see docs/DEPLOY_AWS.md s.11.
set -euo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PULL=1; FAST=0; BACKUP=1; ROLLBACK_ONLY=0
for a in "$@"; do
  case "$a" in
    --no-pull) PULL=0 ;; --fast) FAST=1 ;; --skip-backup) BACKUP=0 ;; --rollback) ROLLBACK_ONLY=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown option $a" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "run with sudo"
install -d -m 700 "$STATE_DIR"
cd "$REPO_DIR"
need_env_file
DRAIN_SECONDS="${FRIDAY_DRAIN_SECONDS:-330}"   # longer than FRIDAY_CALL_MAX_DURATION_S (300)

current_tag() { cat "$STATE_DIR/current_tag" 2>/dev/null || true; }
previous_tag() { cat "$STATE_DIR/previous_tag" 2>/dev/null || true; }
dc() { FRIDAY_TAG="$TAG" GIT_SHA="$TAG" "${COMPOSE[@]}" "$@"; }

was_paused=0
paused_now() { local rc=0; dc exec -T api friday pause --status >/dev/null 2>&1 || rc=$?; [[ $rc -eq 3 ]]; }

restart_services() {          # one at a time, each waits for its healthcheck
  dc up -d --no-deps --wait postgres redis
  dc up -d --no-deps --wait worker-proactive
  dc up -d --no-deps --wait api
  dc up -d --no-deps caddy
}

rollback() {
  local prev; prev="$(previous_tag)"
  [[ -n "$prev" ]] || die "no previous image recorded; cannot roll back automatically"
  docker image inspect "friday:$prev" >/dev/null 2>&1 || die "image friday:$prev is gone; rebuild it: git checkout $prev && $0 --no-pull"
  say "ROLLING BACK to friday:$prev"
  TAG="$prev"; restart_services
  printf '%s' "$prev" > "$STATE_DIR/current_tag"
  ok "rolled back to $prev (database left as is)"
}

if [[ $ROLLBACK_ONLY -eq 1 ]]; then
  TAG="$(current_tag)"; [[ -n "$TAG" ]] || TAG=latest
  rollback
  FRIDAY_TAG="$(current_tag)" bash "$REPO_DIR/deploy/smoke_test.sh" || warn "smoke test failed after rollback: look at docs/DEPLOY_AWS.md s.9"
  exit 0
fi

if [[ $PULL -eq 1 ]]; then
  say "pulling the latest code"
  git -C "$REPO_DIR" diff --quiet || die "local changes in $REPO_DIR; commit/stash them (or use --no-pull)"
  git -C "$REPO_DIR" pull --ff-only
fi
TAG="$(git -C "$REPO_DIR" rev-parse --short=10 HEAD)"
OLD="$(current_tag)"
say "release $TAG (running now: ${OLD:-none})"

say "building the image"
dc build api
docker image inspect "friday:$TAG" >/dev/null

say "checking the configuration with the NEW image (friday check)"
dc run --rm --no-deps -T api check || die "configuration problems listed above; nothing was changed"

if [[ $BACKUP -eq 1 && -n "${OLD}" ]]; then
  say "backing up the database before migrating"
  "$REPO_DIR/deploy/backup.sh" || die "backup failed; fix it or pass --skip-backup knowingly"
fi

dc up -d --no-deps --wait postgres redis
if [[ -n "$OLD" ]] && dc ps --status running --services 2>/dev/null | grep -qx api; then
  if paused_now; then was_paused=1; fi
  if [[ $FAST -eq 0 ]]; then
    say "pausing new calls and letting running calls finish (${DRAIN_SECONDS}s)"
    dc exec -T api friday pause
    sleep "$DRAIN_SECONDS"
  fi
fi

say "running database migrations (alembic upgrade head)"
dc --profile tools run --rm -T migrate || { bad "migration failed; old version keeps running"; dc exec -T api friday pause --resume || true; exit 1; }

say "restarting services one at a time"
restart_services
[[ $was_paused -eq 1 ]] && ok "kill switch left ON as it was before the release" || dc exec -T api friday pause --resume >/dev/null || true

say "smoke test"
if FRIDAY_TAG="$TAG" bash "$REPO_DIR/deploy/smoke_test.sh"; then
  [[ -n "$OLD" && "$OLD" != "$TAG" ]] && printf '%s' "$OLD" > "$STATE_DIR/previous_tag"
  printf '%s' "$TAG" > "$STATE_DIR/current_tag"
  # keep only the current and previous images
  keep=" friday:$TAG friday:$(previous_tag) "
  for img in $(docker images friday --format '{{.Repository}}:{{.Tag}}'); do
    [[ "$keep" == *" $img "* || "$img" == "friday:latest" ]] || docker rmi "$img" >/dev/null 2>&1 || true
  done
  say "DONE: $TAG is live"
else
  bad "smoke test FAILED"
  rollback
  FRIDAY_FRIDAY_TAG="$(current_tag)" bash "$REPO_DIR/deploy/smoke_test.sh" || warn "still failing after rollback"
  die "release $TAG was rolled back. Send the output above to your engineer."
fi
