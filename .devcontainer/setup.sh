#!/bin/bash
# Runs once when the Codespace is created: installs uv and cloudflared, syncs dependencies and creates .env.
# It never prints secrets and never overwrites an existing .env.
set -euo pipefail
pip install --quiet --user uv
export PATH="$HOME/.local/bin:$PATH"
if ! command -v cloudflared >/dev/null 2>&1; then
  sudo curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  sudo chmod +x /usr/local/bin/cloudflared
fi
uv sync
uv run friday init-env || true
echo
echo "READY. Next: open the file named .env in the editor and fill in the empty names, then run:"
echo "  bash deploy/codespace_call.sh"
