#!/usr/bin/env bash
# Build the Robin parent app (android/robin-app): install the Android SDK pieces if missing, run the JVM tests,
# and assemble the debug APK. Works on the founder's machine and in CI. No secrets are read or needed.
#
# Usage:   scripts/build-android.sh            # test + debug APK
#          scripts/build-android.sh --tests    # JVM tests only (no Android SDK needed beyond configuration)
# Env (all optional):
#   ANDROID_HOME / ANDROID_SDK_ROOT   existing SDK; default $HOME/android-sdk (installed on first run)
#   ROBIN_APPLICATION_ID              applicationId build property   (default: gradle.properties value)
#   ROBIN_BRAND_NAME                  app name / brand build property (default: Robin)
#   ROBIN_BASE_URL                    server base URL, https, no trailing slash
# Output:  android/robin-app/app/build/outputs/apk/debug/app-debug.apk
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/android/robin-app"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
PLATFORM="platforms;android-34"
BUILD_TOOLS="build-tools;34.0.0"

if [[ "$(uname -s)" == "Darwin" ]]; then
  CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
fi

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/android-sdk}}"
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"

SDKMANAGER="$SDK/cmdline-tools/latest/bin/sdkmanager"
if [[ ! -x "$SDKMANAGER" ]]; then
  echo "Installing Android command-line tools into $SDK"
  mkdir -p "$SDK/cmdline-tools"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/cmdline.zip" "$CMDLINE_URL"
  unzip -q "$tmp/cmdline.zip" -d "$tmp"
  mv "$tmp/cmdline-tools" "$SDK/cmdline-tools/latest"
  rm -rf "$tmp"
fi

if [[ ! -d "$SDK/platforms/android-34" || ! -d "$SDK/build-tools/34.0.0" ]]; then
  echo "Installing $PLATFORM and $BUILD_TOOLS"
  yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
  "$SDKMANAGER" "$PLATFORM" "$BUILD_TOOLS" >/dev/null
fi

args=()
[[ -n "${ROBIN_APPLICATION_ID:-}" ]] && args+=("-Probin.applicationId=$ROBIN_APPLICATION_ID")
[[ -n "${ROBIN_BRAND_NAME:-}" ]] && args+=("-Probin.brandName=$ROBIN_BRAND_NAME")
[[ -n "${ROBIN_BASE_URL:-}" ]] && args+=("-Probin.baseUrl=$ROBIN_BASE_URL")

cd "$APP"
if [[ "${1:-}" == "--tests" ]]; then
  ./gradlew --no-daemon "${args[@]}" test
else
  ./gradlew --no-daemon "${args[@]}" test assembleDebug
  echo "APK: $APP/app/build/outputs/apk/debug/app-debug.apk"
fi
