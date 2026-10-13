# Friday on Supabase (managed Postgres, Mumbai)

1. Create the organization "Friday" in the Supabase dashboard (https://supabase.com/dashboard/new);
   the MCP cannot create organizations. Then a project "friday-prod", region ap-south-1 (Mumbai).
2. The schema is `schema.sql` (generated from the Alembic migrations: `uv run python -m
   friday.db.regen_supabase_sql`); `rls.sql` switches Row Level Security on for every table.
   Apply both (the lead does it through the Supabase MCP, or paste into the SQL editor).
3. On the server, as root, run `bash /opt/friday/deploy/supabase/set-database-url.sh`. It asks for
   the database password at a HIDDEN prompt (Supabase: Project Settings > Database) and writes
   FRIDAY_DATABASE_URL into /opt/friday/.env. Nothing is printed or committed.
4. `systemctl restart friday`; `friday doctor` checks the connection.
Never put the database password in chat or git (the repo is public).

## Two ways to apply the schema
A. Through the Supabase MCP (needs the connector to see the "Friday" organization: reconnect the
   Supabase connector and tick the Friday org).
B. From the server (works with only the project ref and the database password):
   `bash /opt/friday/deploy/supabase/set-database-url.sh`, then
   `sudo -u friday /home/friday/.local/bin/uv run --directory /opt/friday python -m friday.db.migrate up`
   and `... python -m friday.db.migrate rls`, then `systemctl restart friday`.
