#!/usr/bin/env bash
# Post-deploy smoke test. Read-only: places no calls, sends no messages, spends no money.
#   sudo ./deploy/smoke_test.sh
# Exit code 0 = all required checks passed. Prints [ OK ] / [WARN] / [FAIL] lines, never secrets.
set -uo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
need_env_file

FAILS=0
pass() { ok "$1"; }
fail() { bad "$1"; FAILS=$((FAILS + 1)); }

DOMAIN="$(public_host)"
[[ -n "$DOMAIN" ]] || die "FRIDAY_DOMAIN missing in $FRIDAY_ENV_FILE"
BASE="https://$DOMAIN"
CURL=(curl -sS --max-time 15)

say "1. containers"
for svc in postgres redis api worker-proactive caddy; do
  state="$("${COMPOSE[@]}" ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null | awk -v s="$svc" '$1==s {print $2 " " $3}')"
  if [[ "$state" == running* && "$state" != *unhealthy* && "$state" != *starting* ]]; then pass "$svc: $state"; else fail "$svc: ${state:-not running}"; fi
done

say "2. public health and HTTPS"
body="$("${CURL[@]}" "$BASE/health" 2>&1)" && [[ "$body" == *'"status":"ok"'* || "$body" == *'"status": "ok"'* ]] \
  && pass "GET /health -> ok" || fail "GET $BASE/health -> ${body:0:120}"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "http://$DOMAIN/health" 2>/dev/null)"
[[ "$code" =~ ^30[1278]$ ]] && pass "http:// redirects to https ($code)" || fail "http:// did not redirect (got $code)"
"${CURL[@]}" -sI "$BASE/health" | grep -qi '^strict-transport-security:' && pass "HSTS header present" || fail "HSTS header missing"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/docs" 2>/dev/null)"
[[ "$code" == 404 ]] && pass "unlisted path /docs is not exposed (404)" || fail "/docs answered $code (should be 404)"

say "3. admin health (read-only, needs the admin token)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/admin/health" 2>/dev/null)"
[[ "$code" == 401 || "$code" == 404 ]] && pass "/admin/health refuses callers without a token ($code)" || fail "/admin/health without token answered $code"
tok="$(env_get FRIDAY_ADMIN_TOKEN)"
if [[ -n "$tok" ]]; then
  admin="$(printf 'Authorization: Bearer %s' "$tok" | "${CURL[@]}" -H @- "$BASE/admin/health" 2>&1)"
  summary="$(printf '%s' "$admin" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print(d.get("status"), "mode="+str(d.get("mode")), "queue_depth="+str(d.get("queue_depth")), "dead_letters="+str(d.get("dead_letters")))
sys.exit(0 if d.get("status")=="ok" and not d.get("dead_letters") else 3)' 2>&1)"; rc=$?
  [[ $rc -eq 0 ]] && pass "admin health: $summary" || fail "admin health: $summary"
else fail "FRIDAY_ADMIN_TOKEN not set"; fi

say "4. database migration level"
head_rev="$("${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python api -c \
  'from alembic.script import ScriptDirectory as S; from alembic.config import Config as C; from friday.db.migrate import SCRIPT_LOCATION as L; c=C(); c.set_main_option("script_location", L); print(S.from_config(c).get_current_head())' 2>/dev/null | tail -n1)"
db_rev="$("${COMPOSE[@]}" exec -T postgres psql -U friday -d friday -tAc 'select version_num from alembic_version' 2>/dev/null | tr -d '[:space:]')"
if [[ -n "$head_rev" && "$head_rev" == "$db_rev" ]]; then pass "database is at the latest migration ($db_rev)"
else fail "migration mismatch: code head='${head_rev:-?}' database='${db_rev:-?}' (run: sudo ./deploy/dc.sh --profile tools run --rm migrate)"; fi

say "5. webhook security (bad requests must be rejected)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -H 'X-Hub-Signature-256: sha256=0000000000000000000000000000000000000000000000000000000000000000' \
  -d '{"object":"whatsapp_business_account","entry":[]}' "$BASE/webhooks/whatsapp" 2>/dev/null)"
[[ "$code" == 401 ]] && pass "WhatsApp POST with a bad signature -> 401" || fail "WhatsApp bad signature answered $code (must be 401)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/webhooks/whatsapp" 2>/dev/null)"
[[ "$code" == 401 ]] && pass "WhatsApp POST with no signature -> 401" || fail "WhatsApp unsigned POST answered $code (must be 401)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong-token&hub.challenge=1" 2>/dev/null)"
[[ "$code" == 403 ]] && pass "WhatsApp verify with a wrong token -> 403" || fail "WhatsApp wrong verify token answered $code (must be 403)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/voice/sarvam/inbound?token=bad" 2>/dev/null)"
[[ "$code" == 403 ]] && pass "Vobiz webhook with a bad token -> 403" || fail "Vobiz bad token answered $code (must be 403)"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' --http1.1 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$BASE/voice/sarvam/media?key=x&token=bad" 2>/dev/null)"
[[ "$code" != 101 ]] && pass "media WebSocket with a bad token is refused ($code)" || fail "media WebSocket accepted a bad token"

say "6. configuration and the Vobiz account (read-only: friday check --live)"
if "${COMPOSE[@]}" run --rm --no-deps -T api check --live; then pass "friday check --live"; else fail "friday check --live reported problems (see above)"; fi

say "7. nothing but 80/443 (and SSH) listens on the internet"
exposed="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Ev '^(127\.|\[::1\]|\[::\]:22$|0\.0\.0\.0:22$|\*:22$)' | sed -E 's/.*:([0-9]+)$/\1/' | sort -un | grep -Ev '^(80|443|53)$' || true)"
[[ -z "$exposed" ]] && pass "only ports 80 and 443 are open (plus SSH)" || fail "unexpected listening ports: $(echo $exposed)"

say "8. kill switch"
rc=0; "${COMPOSE[@]}" exec -T api friday pause --status >/tmp/.friday-pause 2>&1 || rc=$?
if [[ $rc -eq 0 ]]; then pass "kill switch is OFF (Friday is running)"; elif [[ $rc -eq 3 ]]; then warn "kill switch is ON (Friday is PAUSED): $(cat /tmp/.friday-pause)"; else fail "could not read the kill switch"; fi
rm -f /tmp/.friday-pause

echo
if [[ $FAILS -eq 0 ]]; then printf 'SMOKE TEST PASSED\n'; exit 0; fi
printf 'SMOKE TEST FAILED: %d check(s)\n' "$FAILS" >&2; exit 1
