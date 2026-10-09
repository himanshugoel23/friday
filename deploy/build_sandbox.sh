#!/usr/bin/env bash
# Build the friday image inside the Claude cloud sandbox, where ghcr.io is blocked and build
# containers do not trust the egress proxy CA. NOT needed on a normal server: use update.sh there.
# The repo Dockerfile is untouched; a temporary copy installs the same uv from PyPI and trusts the
# proxy CA in the builder stage only (never in the runtime image). TLS verification stays on.
# Usage: deploy/build_sandbox.sh [tag]     (start the daemon first: `dockerd &`)
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-friday:beta}"
CA=/root/.ccr/ca-bundle.crt
[[ -f "$CA" ]] || { echo "no $CA: this script is only for the Claude cloud sandbox" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/ca"; cp "$CA" "$TMP/ca/"
UV_VER="$(grep -oP 'astral-sh/uv:\K[0-9.]+' Dockerfile)"
python3 - "$TMP" "$UV_VER" <<'PY'
import sys
tmp, ver = sys.argv[1:3]
s = open("Dockerfile").read()
old = f"COPY --from=ghcr.io/astral-sh/uv:{ver} /uv /uvx /usr/local/bin/"
assert old in s, "Dockerfile uv line changed; update this script"
new = ("COPY --from=ca ca-bundle.crt /etc/proxy-ca.crt\n"
       "ENV SSL_CERT_FILE=/etc/proxy-ca.crt PIP_CERT=/etc/proxy-ca.crt REQUESTS_CA_BUNDLE=/etc/proxy-ca.crt\n"
       f"RUN pip install --no-cache-dir uv=={ver}")
open(f"{tmp}/Dockerfile", "w").write(s.replace(old, new))
PY
docker build -f "$TMP/Dockerfile" --build-context ca="$TMP/ca" \
  --build-arg GIT_SHA="$(git rev-parse --short HEAD)" -t "$TAG" .
echo "built $TAG"
