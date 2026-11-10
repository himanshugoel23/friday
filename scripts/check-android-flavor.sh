#!/usr/bin/env bash
# Print an APK's permission list (aapt2) and fail if it does not match its flavor.
#   lite: EXACTLY INTERNET + RECORD_AUDIO; no service element, no BubbleService/BootReceiver, nothing about overlay,
#         foreground service, boot or notifications.
#   full: exactly the eight permissions of docs/ROBIN_ANDROID_APP.md (INTERNET, RECORD_AUDIO + the six bubble ones)
#         and both bubble components.
# Usage: scripts/check-android-flavor.sh lite|full path/to/app.apk
# Env:   AAPT2 = path to aapt2 (default: newest under $ANDROID_HOME/build-tools). Tests point it at a fake.
set -euo pipefail
flavor="${1:?usage: check-android-flavor.sh lite|full APK}"
apk="${2:?usage: check-android-flavor.sh lite|full APK}"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-${HOME:-/nonexistent}/android-sdk}}"
AAPT2="${AAPT2:-$(ls "$SDK"/build-tools/*/aapt2 2>/dev/null | sort -V | tail -1 || true)}"
[[ -n "$AAPT2" ]] || { echo "aapt2 not found (set AAPT2 or ANDROID_HOME)"; exit 2; }

perms="$("$AAPT2" dump permissions "$apk" | sed -n "s/^uses-permission[a-z0-9-]*: name='\([^']*\)'.*/\1/p" | sort -u)"
tree="$("$AAPT2" dump xmltree --file AndroidManifest.xml "$apk")"
echo "== $flavor: $apk"
echo "permissions:"
sed 's/^/  /' <<<"$perms"

base="android.permission.INTERNET android.permission.RECORD_AUDIO"
bubble="android.permission.SYSTEM_ALERT_WINDOW android.permission.FOREGROUND_SERVICE android.permission.FOREGROUND_SERVICE_SPECIAL_USE android.permission.FOREGROUND_SERVICE_MICROPHONE android.permission.POST_NOTIFICATIONS android.permission.RECEIVE_BOOT_COMPLETED"
case "$flavor" in
  lite) want="$base" ;;
  full) want="$base $bubble" ;;
  *) echo "unknown flavor $flavor"; exit 2 ;;
esac
expected="$(tr ' ' '\n' <<<"$want" | sort -u)"
fail=0
if [[ "$perms" != "$expected" ]]; then
  echo "FAIL: permission set differs. unexpected: [$(comm -23 <(echo "$perms") <(echo "$expected") | tr '\n' ' ')] missing: [$(comm -13 <(echo "$perms") <(echo "$expected") | tr '\n' ' ')]"
  fail=1
fi
if [[ "$flavor" == "lite" ]]; then
  if grep -Eq 'BubbleService|BootReceiver|E: service|BOOT_COMPLETED|foregroundServiceType' <<<"$tree"; then
    echo "FAIL: lite manifest contains a bubble/boot/foreground-service component"
    fail=1
  fi
else
  if ! { grep -q 'BubbleService' <<<"$tree" && grep -q 'BootReceiver' <<<"$tree"; }; then
    echo "FAIL: full manifest lacks BubbleService/BootReceiver"
    fail=1
  fi
fi
if [[ $fail -eq 0 ]]; then echo "OK: $flavor manifest matches"; else exit 1; fi
