#!/bin/bash
# Friday: where does the time go between THIS server and the AI vendors? (read-only, a few tiny requests)
#   bash /opt/friday/deploy/latency_probe.sh
# Keys are read from /opt/friday/.env and used only inside curl; they are never printed.
ENVF=/opt/friday/.env
getv() { grep "^$1=." "$ENVF" | tail -1 | cut -d= -f2-; }
OPENAI_KEY="$(getv OPENAI_API_KEY)"; EL_KEY="$(getv ELEVENLABS_API_KEY)"; SARVAM_KEY="$(getv SARVAM_API_KEY)"
fmt='dns %{time_namelookup}s  tcp %{time_connect}s  tls %{time_appconnect}s  first-byte %{time_starttransfer}s  total %{time_total}s  http %{http_code}\n'
run() { # name, then curl args
  local name="$1"; shift
  for i in 1 2 3; do printf '%-26s' "$name #$i"; curl -s -o /dev/null -m 20 -w "$fmt" "$@"; done
}
echo "== where is this server, and how far is OpenAI?"
curl -s -m 5 https://ipinfo.io/json 2>/dev/null | grep -E '"(city|region|country|org)"' | tr -d '\n'; echo
echo "== OpenAI: GET /v1/models (network only)"
[ -n "$OPENAI_KEY" ] && run "openai models" https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_KEY"
echo "== OpenAI: tiny chat completion (the call-turn model, no reasoning, 8 tokens)"
[ -n "$OPENAI_KEY" ] && run "openai gpt-5.4-mini" https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.4-mini","messages":[{"role":"user","content":"Reply with the word ok"}],"max_completion_tokens":8,"reasoning_effort":"none"}'
echo "== ElevenLabs: text-to-speech stream, first byte"
[ -n "$EL_KEY" ] && run "elevenlabs flash stream" "https://api.elevenlabs.io/v1/text-to-speech/OtEfb2LVzIE45wdYe54M/stream?output_format=pcm_8000" \
  -H "xi-api-key: $EL_KEY" -H "Content-Type: application/json" \
  -d '{"text":"Haan ji, bataiye.","model_id":"eleven_flash_v2_5"}'
echo "== Sarvam: text-to-speech stream, first byte"
[ -n "$SARVAM_KEY" ] && run "sarvam tts stream" https://api.sarvam.ai/text-to-speech/stream \
  -H "api-subscription-key: $SARVAM_KEY" -H "Content-Type: application/json" \
  -d '{"text":"Haan ji, bataiye.","target_language_code":"hi-IN","speaker":"ritu","model":"bulbul:v3","speech_sample_rate":8000,"output_audio_codec":"wav"}'
echo "Read first-byte: that is the wait you feel. tcp+tls = connection cost (our code reuses a warm connection)."
