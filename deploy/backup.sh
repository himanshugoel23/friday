#!/usr/bin/env bash
# Nightly Postgres backup -> S3 (ap-south-1). Run from cron as root (see docs/DEPLOY_AWS.md step 12):
#   17 20 * * *  root  /opt/friday/deploy/backup.sh >> /var/log/friday-backup.log 2>&1
# (20:17 UTC = 01:47 IST.)  Safe to run by hand any time; also called by update.sh before a release.
#
# What it does: pg_dump (custom format, compressed) -> verify it is readable -> upload to
# s3://$BACKUP_BUCKET/postgres/ with server-side encryption -> keep 3 local copies.
# Old backups expire by the bucket lifecycle rule (30 days), nothing here deletes from S3.
#
# Config: /etc/friday/backup.env (chmod 600), NOT in git:
#   BACKUP_BUCKET=friday-backups-yourname-mumbai
#   AWS_ACCESS_KEY_ID=...            # IAM user "friday-backup" (policy in docs/DEPLOY_AWS.md)
#   AWS_SECRET_ACCESS_KEY=...
#   AWS_DEFAULT_REGION=ap-south-1
#   BACKUP_ENDPOINT_URL=https://blr1.digitaloceanspaces.com   # only for non-AWS S3-compatible storage
#   HEALTHCHECK_URL=                 # optional: a "dead man's switch" URL pinged only on success
#
# Does NOT back up /etc/friday/.env (it holds the encryption keys): keep an offline copy yourself.
set -euo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

BACKUP_ENV="${FRIDAY_BACKUP_ENV:-/etc/friday/backup.env}"
LOCAL_DIR="${FRIDAY_BACKUP_DIR:-/var/backups/friday}"
KEEP_LOCAL="${FRIDAY_BACKUP_KEEP_LOCAL:-3}"

[[ -r "$BACKUP_ENV" ]] || die "missing $BACKUP_ENV (see the header of this script)"
set -a; # shellcheck disable=SC1090
source "$BACKUP_ENV"; set +a
: "${BACKUP_BUCKET:?BACKUP_BUCKET not set in $BACKUP_ENV}"
command -v aws >/dev/null || die "aws CLI not installed (docs/DEPLOY_AWS.md step 12)"
need_env_file

exec 9>/var/lock/friday-backup.lock
flock -n 9 || die "another backup is running"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$LOCAL_DIR/friday-$stamp.dump"
install -d -m 700 "$LOCAL_DIR"
trap 'rm -f "$file.partial"' EXIT

say "dumping database"
"${COMPOSE[@]}" exec -T postgres pg_dump -U friday -d friday --format=custom --compress=6 --no-owner > "$file.partial"
size=$(stat -c %s "$file.partial")
[[ "$size" -gt 20000 ]] || die "dump is suspiciously small ($size bytes)"
"${COMPOSE[@]}" exec -T postgres pg_restore --list < "$file.partial" >/dev/null || die "dump is not readable by pg_restore"
mv "$file.partial" "$file"; chmod 600 "$file"
ok "dump $(basename "$file") ($((size / 1024)) KiB) verified"

say "uploading to s3://$BACKUP_BUCKET/postgres/"
aws ${BACKUP_ENDPOINT_URL:+--endpoint-url "$BACKUP_ENDPOINT_URL"} s3 cp "$file" "s3://$BACKUP_BUCKET/postgres/$(basename "$file")" --only-show-errors
aws ${BACKUP_ENDPOINT_URL:+--endpoint-url "$BACKUP_ENDPOINT_URL"} s3api head-object --bucket "$BACKUP_BUCKET" --key "postgres/$(basename "$file")" >/dev/null
ok "uploaded and confirmed"

# keep the newest N local copies
# shellcheck disable=SC2012
ls -1t "$LOCAL_DIR"/friday-*.dump 2>/dev/null | tail -n +"$((KEEP_LOCAL + 1))" | xargs -r rm -f --

if [[ -n "${HEALTHCHECK_URL:-}" ]]; then curl -fsS -m 10 "$HEALTHCHECK_URL" >/dev/null || warn "healthcheck ping failed"; fi
say "backup finished"
