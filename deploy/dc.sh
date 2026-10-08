#!/usr/bin/env bash
# Short-hand for the production compose file, with the right env file and image tag.
#   sudo ./deploy/dc.sh ps
#   sudo ./deploy/dc.sh logs -f --tail=100 api
#   sudo ./deploy/dc.sh exec api friday pause          # kill switch ON  (--resume = OFF)
set -euo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
exec "${COMPOSE[@]}" "$@"
