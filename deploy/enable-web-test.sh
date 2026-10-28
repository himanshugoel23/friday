#!/bin/bash
# Friday: switch the WEB TEST on (Friday Web channel + every feature switch that is safe in the pilot).
# Run as root:   bash /opt/friday/deploy/enable-web-test.sh          (turn on; safe to run again)
# Undo:          bash /opt/friday/deploy/enable-web-test.sh off
#
# Only NON-secret switches are written to /opt/friday/.env. It never asks for, reads out or prints a
# value: the report at the end lists key NAMES with on/off (or set/missing). Keys (OpenAI, Sarvam,
# Google Places, the web admin token ...) are NOT touched: use deploy/set-key.sh for those.
#
# What "on" does, in order:
#   1. FRIDAY_WEB_CHANNEL_ENABLED=true, FRIDAY_PROFILE=pilot (kept), FRIDAY_INVITE_ONLY=false,
#      FRIDAY_CHATBOT_ONBOARDING=true + FRIDAY_PILOT=true (the real first-run chat, guardrails, parity)
#   2. feature switches (see FEATURES_ON below). Left OFF on purpose: FRIDAY_REFUND_CHASE_CALLS (its
#      spoken lines are not approved), FRIDAY_FAMILY_DRIVE_SHARING_ENABLED, FRIDAY_PARITY_DIGEST,
#      FRIDAY_PARITY_NUDGES, FRIDAY_PARITY_ESCALATION (not wired to the live path, see
#      docs/WEB_TEST_STATUS.md)
#   3. FRIDAY_VENDOR_CALL_REDIRECT_TO = the FIRST number already in FRIDAY_PILOT_ALLOWED_NUMBERS
#      (the web guard then rings the tester's own phone for any call); web caps = 0 (unlimited)
#   4. installs ffmpeg if missing (voice notes from iPhone/Android), runs deploy/web-https.sh,
#      restarts the friday service, prints the report.
# "off": web channel + all feature switches false, invite-only true again, web route removed.
# It leaves FRIDAY_PROFILE, FRIDAY_CHATBOT_ONBOARDING, FRIDAY_PILOT and every key as they are.
set -euo pipefail
# FRIDAY_ENV_FILE is an override for tests only (tests/webchat/test_enable_web_test.py), without root.
[ "$(id -u)" = 0 ] || [ -n "${FRIDAY_ENV_FILE:-}" ] || { echo "Run as root"; exit 1; }
MODE=on
case "${1:-}" in
  "") ;;
  off) MODE=off ;;
  *) echo "Usage: bash enable-web-test.sh [off]"; exit 1 ;;
esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF: run small-server.sh first"; exit 1; }

# One pass over the env file: replace a key in place (or append it), strip whitespace from values,
# keep everything else byte for byte. Prints only NAMES and on/off / set/missing.
FRIDAY_MODE="$MODE" python3 - "$ENVF" <<'PY'
import os
import re
import sys

path = sys.argv[1]
mode = os.environ["FRIDAY_MODE"]
raw = open(path).read().splitlines()


def get(key):
    val = ""
    for line in raw:
        if line.startswith(key + "="):
            val = "".join(line.split("=", 1)[1].split()).strip("\"'")
    return val


def put(key, val):
    val = "".join(str(val).split())
    out, done = [], False
    for line in raw:
        if line.startswith(key + "="):
            if not done:
                out.append(f"{key}={val}")
                done = True
            continue  # a duplicate line of the same key is dropped
        out.append(line)
    if not done:
        out.append(f"{key}={val}")
    raw[:] = out


# switches that are safe in the pilot (the web guard keeps every call on the tester's own number)
FEATURES_ON = [
    "FRIDAY_PROOF_ENABLED", "FRIDAY_DOCS_ENABLED", "FRIDAY_FAMILY_DRIVE_ENABLED", "FRIDAY_TRIPS_ENABLED",
    "FRIDAY_REFUNDS_ENABLED", "FRIDAY_URGENT_ESCALATION_ENABLED", "FRIDAY_RECEPTIONIST_ENABLED",
    "FRIDAY_PARITY_INVITES", "FRIDAY_PARITY_RIDE_LINKS", "FRIDAY_PARITY_INR_ONLY", "FRIDAY_PARITY_STATUS",
    "FRIDAY_GUARDRAILS_NEW_CATEGORIES", "FRIDAY_BROWSER_LOGIN_OTP_IN_CHAT",
]
# stay off in both modes (calls with unapproved lines / not wired to the live path / sharing)
ALWAYS_OFF = [
    "FRIDAY_REFUND_CHASE_CALLS", "FRIDAY_FAMILY_DRIVE_SHARING_ENABLED", "FRIDAY_PARITY_DIGEST",
    "FRIDAY_PARITY_NUDGES", "FRIDAY_PARITY_ESCALATION",
]
CAPS = ["FRIDAY_WEB_MAX_CALLS_PER_DAY", "FRIDAY_WEB_MAX_SPEND_INR", "FRIDAY_WEB_GLOBAL_MAX_SPEND_INR"]

problem = None
if mode == "on":
    nums = [n for n in re.split(r"[,;\[\]\"'\s]+", get("FRIDAY_PILOT_ALLOWED_NUMBERS")) if n]
    if not nums:
        problem = "FRIDAY_PILOT_ALLOWED_NUMBERS is empty: add the founder's number first (deploy/setenv.sh)."
    else:
        put("FRIDAY_PROFILE", "pilot")
        put("FRIDAY_WEB_CHANNEL_ENABLED", "true")
        put("FRIDAY_INVITE_ONLY", "false")
        put("FRIDAY_CHATBOT_ONBOARDING", "true")
        put("FRIDAY_PILOT", "true")
        put("FRIDAY_VENDOR_CALL_REDIRECT_TO", nums[0])
        for k in CAPS:
            put(k, "0")
        for k in FEATURES_ON:
            put(k, "true")
        put("FRIDAY_DOCS_VISION_PROVIDER", "openai")  # reads photos/PDFs with the existing OPENAI_API_KEY
        for k in ALWAYS_OFF:
            put(k, "false")
else:
    put("FRIDAY_WEB_CHANNEL_ENABLED", "false")
    put("FRIDAY_INVITE_ONLY", "true")
    for k in FEATURES_ON + ALWAYS_OFF:
        put(k, "false")
    put("FRIDAY_DOCS_VISION_PROVIDER", "none")

if problem:
    print(problem)
    sys.exit(3)
open(path, "w").write("\n".join(raw) + "\n")


def onoff(key):
    v = get(key).lower()
    return "on" if v in ("true", "1", "yes", "on") else "off"


def present(key):
    return "set" if get(key) else "missing"


print(f"web test: {mode.upper()}  (key names only; no values are printed)")
for k in ["FRIDAY_WEB_CHANNEL_ENABLED", "FRIDAY_INVITE_ONLY", "FRIDAY_CHATBOT_ONBOARDING", "FRIDAY_PILOT"] + FEATURES_ON + ALWAYS_OFF:
    print(f"  {k:<40} {onoff(k)}")
print(f"  {'FRIDAY_PROFILE':<40} {'pilot' if get('FRIDAY_PROFILE') == 'pilot' else 'NOT pilot'}")
print(f"  {'FRIDAY_DOCS_VISION_PROVIDER':<40} {get('FRIDAY_DOCS_VISION_PROVIDER') or 'none'}")
for k in ["FRIDAY_VENDOR_CALL_REDIRECT_TO", "FRIDAY_PILOT_ALLOWED_NUMBERS", "FRIDAY_PUBLIC_BASE_URL",
          "FRIDAY_WEB_ADMIN_TOKEN", "OPENAI_API_KEY", "SARVAM_API_KEY", "GOOGLE_PLACES_API_KEY"]:
    print(f"  {k:<40} {present(k)}")
print("  web caps (calls/day, INR/day, global INR/day)   " + ("unlimited (0)" if all(get(k) == "0" for k in CAPS) else "check"))
PY

if id friday >/dev/null 2>&1; then chown friday:friday "$ENVF"; fi
chmod 600 "$ENVF"

if [ "$MODE" = on ]; then
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "installing ffmpeg (needed to decode voice notes)..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg >/dev/null 2>&1 || echo "WARNING: ffmpeg install failed; voice notes may not work"
  fi
  command -v ffmpeg >/dev/null 2>&1 && echo "ffmpeg: present" || echo "ffmpeg: MISSING"
  bash "${FRIDAY_WEB_HTTPS_SCRIPT:-$APP/deploy/web-https.sh}" || echo "WARNING: web-https.sh failed (is Caddy installed?); the default handler may still forward /web"
else
  bash "${FRIDAY_WEB_HTTPS_SCRIPT:-$APP/deploy/web-https.sh}" --off || echo "WARNING: web-https.sh --off failed"
fi

systemctl restart friday
sleep 2
echo "friday service: $(systemctl is-active friday 2>/dev/null || true)"
if [ "$MODE" = on ]; then
  echo "Next: cd $APP && sudo -u friday /home/friday/.local/bin/uv run friday web invite --name <Name> --phone <+91 number>"
  echo "      (prints the personal link once). Then: sudo -u friday /home/friday/.local/bin/uv run friday doctor"
  echo "Key checks: OPENAI_API_KEY and SARVAM_API_KEY must say 'set' above (deploy/set-key.sh <NAME> if not)."
fi
