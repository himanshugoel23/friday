# Friday on Supabase (managed Postgres)

Status (13 Oct 2026): project `zxbiapcppbfnctndmnab` in the Supabase organization "Friday"
(region ap-southeast-1, Postgres 17, free plan). The full schema (Alembic 0001 to 0005, 88 tables
including the monthly partitions) is applied and Row Level Security is ON for every table (no
policies: the public Data API reads nothing; only the server's database owner role can).

Connect the server (the only manual step, as root on the server):

    cd /opt/friday && git pull --ff-only origin claude/friday-phase-1
    bash /opt/friday/deploy/supabase/set-database-url.sh
    systemctl restart friday

The script asks for the project ref (default is ours), the region, and the database password
(Supabase: Project Settings > Database > Reset database password) at a HIDDEN prompt, tests the
three ways to reach the database and writes FRIDAY_DATABASE_URL into /opt/friday/.env. Never put
the password in chat or git (the repo is public).

Files: `schema.sql` (generated: `uv run python -m friday.db.regen_supabase_sql`), `rls.sql`
(same effect as `python -m friday.db.migrate rls`).

Later: move to a Mumbai (ap-south-1) project on the Pro plan before real users (free plans pause
after a week of inactivity, have no backups and a 500 MB limit; Singapore adds about 60 ms per
query from Bangalore). The temporary `http` extension used to apply the schema could not be
dropped by the SQL API (the call hung): disable it in Dashboard > Database > Extensions.
