# shellcheck shell=bash
# Shared helpers for deploy/*.sh (sourced, not run). Never prints secret values.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FRIDAY_ENV_FILE="${FRIDAY_ENV_FILE:-/etc/friday/.env}"
STATE_DIR="${FRIDAY_STATE_DIR:-/var/lib/friday-deploy}"
export FRIDAY_TAG="${FRIDAY_TAG:-$(cat "$STATE_DIR/current_tag" 2>/dev/null || echo latest)}"
COMPOSE=(docker compose --env-file "$FRIDAY_ENV_FILE" -f "$REPO_DIR/deploy/docker-compose.prod.yml")

say()  { printf '\n==> %s\n' "$*"; }
ok()   { printf '  [ OK ] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*" >&2; }
bad()  { printf '  [FAIL] %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

need_env_file() {
  [[ -r "$FRIDAY_ENV_FILE" ]] || die "cannot read $FRIDAY_ENV_FILE (run with sudo, or create it: docs/DEPLOY_AWS.md step 9)"
  if grep -q 'CHANGE_ME' "$FRIDAY_ENV_FILE"; then
    die "$FRIDAY_ENV_FILE still contains CHANGE_ME placeholders. Fill them in first."
  fi
}

# env_get NAME -> value (without printing anything else). Handles plain KEY=value lines.
env_get() { grep -E "^$1=" "$FRIDAY_ENV_FILE" | tail -n1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//' ; }

public_host() { env_get FRIDAY_DOMAIN; }
