#!/bin/bash
# One command for the free Codespaces trial: starts the temporary public address (Cloudflare quick tunnel),
# writes it into .env, runs the read-only checks, then places the test call to YOUR allowed number.
# Usage: bash deploy/codespace_call.sh [--simulate]
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
[ -f .env ] || uv run friday init-env

if [ "${1:-}" = "--simulate" ]; then
  exec uv run friday livecall --to +910000000000 --simulate
fi

# Show only the NAMES of the values that are still empty (never the values).
missing=$(python3 - <<'PY'
import re
vals = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.rstrip("\n"))
    if m: vals[m.group(1)] = m.group(2).split("#")[0].strip().strip('"').strip("'")
need = ["SARVAM_API_KEY", "SARVAM_TELEPHONY_AUTH_ID", "SARVAM_TELEPHONY_AUTH_TOKEN",
        "SARVAM_CALLER_IDS", "FRIDAY_PILOT_ALLOWED_NUMBERS"]
llm = vals.get("OPENAI_API_KEY") or vals.get("ANTHROPIC_API_KEY") or vals.get("FRIDAY_LLM_PROVIDER") == "fake"
print(" ".join([k for k in need if not vals.get(k)] + ([] if llm else ["OPENAI_API_KEY (or ANTHROPIC_API_KEY)"])))
PY
)
if [ -n "$missing" ]; then
  echo "Still empty in .env: $missing"
  echo "Open .env in the editor, fill those in (no quotes, no spaces), save, and run this command again."
  exit 1
fi

to=$(python3 - <<'PY'
import re
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^FRIDAY_PILOT_ALLOWED_NUMBERS=(.*)$", line.rstrip("\n"))
    if m:
        v = m.group(1).split("#")[0].strip().strip('"').strip("'").strip("[]").replace('"', "")
        print(v.split(",")[0].strip()); break
PY
)

log=$(mktemp)
cloudflared tunnel --no-autoupdate --url http://localhost:8000 >"$log" 2>&1 &
tunnel_pid=$!
trap 'kill $tunnel_pid 2>/dev/null' EXIT
url=""
for _ in $(seq 1 30); do
  url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$log" | grep -v '^https://api\.' | head -1 || true)
  [ -n "$url" ] && break
  sleep 2
done
[ -n "$url" ] || { echo "The temporary public address did not start. Try again in a minute."; exit 1; }
echo "Temporary public address: $url"

URL="$url" python3 - <<'PY'
import os, re
url = os.environ["URL"]
lines = open(".env", encoding="utf-8").read().splitlines()
out, done = [], False
for line in lines:
    if line.startswith("FRIDAY_PUBLIC_BASE_URL="):
        out.append(f"FRIDAY_PUBLIC_BASE_URL={url}"); done = True
    else:
        out.append(line)
if not done: out.append(f"FRIDAY_PUBLIC_BASE_URL={url}")
open(".env", "w", encoding="utf-8").write("\n".join(out) + "\n")
PY

echo "Running the read-only checks..."
uv run friday doctor || { echo "Fix what doctor lists above, then run this command again."; exit 1; }
echo
echo "About to call $to from your Vobiz number (a few rupees). Type YES when asked."
uv run friday livecall --to "$to"
