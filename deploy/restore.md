# Restore the Friday database from a backup

Do a **restore drill once before real users** (section A, on a scratch copy). In a real
emergency use section B. Nothing here needs engineering skill, but go slowly and read each
step. All commands run on the server (`ssh ubuntu@<your-static-ip>`), in `/opt/friday`.

What a backup contains: the Postgres database (users, tasks, messages, call logs). Sensitive
columns are encrypted with `FRIDAY_FIELD_KEY`, so **a backup is useless without the same
`/etc/friday/.env` keys**. Keep an offline copy of that file (password manager).

## A. Restore drill (safe: nothing live is touched)

```bash
cd /opt/friday
# 1. fetch the newest backup from S3 (needs /etc/friday/backup.env)
set -a; source /etc/friday/backup.env; set +a
aws s3 ls "s3://$BACKUP_BUCKET/postgres/" | tail -n 3          # pick a file name
aws s3 cp "s3://$BACKUP_BUCKET/postgres/friday-YYYYMMDDTHHMMSSZ.dump" /tmp/restore.dump

# 2. start a throw-away database next to the real one
docker run -d --name friday-restore-drill -e POSTGRES_PASSWORD=drill postgres:16-alpine
sleep 8
docker exec -i friday-restore-drill createdb -U postgres friday_drill
docker exec -i friday-restore-drill pg_restore -U postgres -d friday_drill --no-owner < /tmp/restore.dump

# 3. look at it
docker exec friday-restore-drill psql -U postgres -d friday_drill -c "select version_num from alembic_version;"
docker exec friday-restore-drill psql -U postgres -d friday_drill -c "select count(*) as users from users;"

# 4. clean up
docker rm -f friday-restore-drill; shred -u /tmp/restore.dump
```
Pass = no errors, a revision number, and a user count that looks right.

## B. Real restore (the live database is damaged or lost)

1. Stop new work and the app (keep the database running):
   ```bash
   docker compose --env-file /etc/friday/.env -f deploy/docker-compose.prod.yml stop caddy api worker-proactive
   ```
2. Take one more dump of the damaged database if it still starts (`sudo ./deploy/backup.sh`), so you can go back.
3. Download the backup you want (as in A.1) to `/tmp/restore.dump`.
4. Replace the database:
   ```bash
   C="docker compose --env-file /etc/friday/.env -f deploy/docker-compose.prod.yml"
   $C exec -T postgres psql -U friday -d postgres -c "DROP DATABASE IF EXISTS friday WITH (FORCE);"
   $C exec -T postgres psql -U friday -d postgres -c "CREATE DATABASE friday OWNER friday;"
   $C exec -T postgres pg_restore -U friday -d friday --no-owner < /tmp/restore.dump
   ```
5. Bring the app back and run the migrations (a no-op if the backup is current):
   ```bash
   $C --profile tools run --rm migrate
   $C up -d
   sudo ./deploy/smoke_test.sh
   shred -u /tmp/restore.dump
   ```
6. Tell the testers: messages sent after the backup time may be missing (the backup is nightly,
   so up to ~24 hours). WhatsApp may re-deliver recent messages by itself.

If the whole server is gone: create a new instance (docs/DEPLOY_AWS.md steps 5-11), put the saved
`.env` back, start only `postgres` (`$C up -d postgres`), then do step B.3-B.5.
