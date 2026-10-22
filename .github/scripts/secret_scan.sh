#!/usr/bin/env bash
# Secret scan for a PUBLIC repo. Scans tracked files (or the files given) for key-shaped strings and
# checks that .env, var/ and database files are not tracked. Prints file:line and the PATTERN NAME
# only, never the matched text. Exit 1 on any finding.
set -u
cd "$(git rev-parse --show-toplevel)"
fail=0

bad_tracked=$(git ls-files | grep -E '(^|/)\.env($|\.)|(^|/)var/|\.(db|sqlite3?|pem|key|p12)$' \
  | grep -vE '(^|/)\.env\.example$' || true)
if [ -n "$bad_tracked" ]; then
  echo "FAIL: files that must never be tracked are tracked:"; echo "$bad_tracked"; fail=1
fi

declare -A PATTERNS=(
  [anthropic_key]='sk-ant-[A-Za-z0-9_-]{20,}'
  [openai_key]='sk-(proj-)?[A-Za-z0-9]{32,}'
  [aws_access_key]='AKIA[0-9A-Z]{16}'
  [github_token]='gh[pousr]_[A-Za-z0-9]{30,}'
  [slack_token]='xox[baprs]-[A-Za-z0-9-]{10,}'
  [google_api_key]='AIza[0-9A-Za-z_-]{35}'
  [private_key_block]='-----BEGIN [A-Z ]*PRIVATE KEY-----'
  [meta_token]='EAA[A-Za-z0-9]{100,}'
  [db_url_password]='(postgres(ql)?|redis|mysql)(\+[a-z]+)?://[^:/@ ]+:[^@ ${}<>*]{6,}@[A-Za-z0-9.-]+'
)
# lines that are clearly placeholders / test fixtures are allowed with this marker
ALLOW='secret-scan: allow'

files=$(git ls-files | grep -vE '^(uv\.lock|\.github/scripts/secret_scan\.sh)$|\.(png|jpg|wav|mp3|ogg|pdf|ico)$')
for name in "${!PATTERNS[@]}"; do
  hits=$(echo "$files" | xargs -r grep -HInE -e "${PATTERNS[$name]}" 2>/dev/null \
    | grep -v "$ALLOW" | cut -d: -f1,2 || true)
  if [ -n "$hits" ]; then
    echo "FAIL: pattern '$name' matched at:"; echo "$hits" | sed 's/^/  /'; fail=1
  fi
done

if [ "$fail" -eq 0 ]; then echo "secret scan: clean"; fi
exit "$fail"
