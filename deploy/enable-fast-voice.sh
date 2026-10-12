#!/bin/bash
# Friday: turn on the fast voice settings in /opt/friday/.env (idempotent; run as root on the server).
#   bash /opt/friday/deploy/enable-fast-voice.sh [elevenlabs-voice-id]
# Sets: streaming speech-to-text ON, ElevenLabs voice (default Zara), and asks for the ElevenLabs key
# only if it is not in .env yet (typed silently, never shown). Prints key NAMES only, never values.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
ENVF=/opt/friday/.env
[ -f "$ENVF" ] || { echo "$ENVF not found"; exit 1; }
[ -z "$(tail -c1 "$ENVF")" ] || echo >> "$ENVF"      # make sure the file ends with a newline
setv() { if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else echo "$1=$2" >> "$ENVF"; fi; }
setv FRIDAY_VOICE_STREAM_STT true
setv FRIDAY_TTS_PROVIDER elevenlabs
setv ELEVENLABS_VOICE_ID "${1:-OtEfb2LVzIE45wdYe54M}"
if ! grep -q "^ELEVENLABS_API_KEY=." "$ENVF"; then
  read -rs -p "ElevenLabs API key (typing is hidden): " K; echo
  [ -n "$K" ] && echo "ELEVENLABS_API_KEY=$K" >> "$ENVF"
  unset K
fi
chown friday:friday "$ENVF"; chmod 600 "$ENVF"
echo "In .env now (names only):"
grep -oE "^(FRIDAY_VOICE_STREAM_STT|FRIDAY_TTS_PROVIDER|ELEVENLABS_VOICE_ID|ELEVENLABS_API_KEY|SARVAM_API_KEY|OPENAI_API_KEY)=" "$ENVF" | sort
history -c 2>/dev/null || true
