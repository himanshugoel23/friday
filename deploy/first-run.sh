#!/usr/bin/env bash
# Friday: first-run helper for a fresh Ubuntu 24.04 Lightsail server (iPad-friendly, no nano).
#
#   bash /opt/friday/deploy/first-run.sh                  # TEST server (default): pilot profile, free sslip.io HTTPS name
#   bash /opt/friday/deploy/first-run.sh --prod           # private-beta production (beta profile, your own domain)
#   bash /opt/friday/deploy/first-run.sh my-branch        # use another git branch (default: claude/friday-phase-1)
#   bash /opt/friday/deploy/first-run.sh --force          # start /etc/friday/.env again from the template (asks first,
#                                                         # keeps a timestamped backup of the old file)
#
# Run it as the normal `ubuntu` user (NOT with sudo). It is safe to run again: it keeps every value
# that is already set, and a re-run is also how you deploy a newer version (git pull, then update.sh).
#
# Secrets are typed with HIDDEN input, written to /etc/friday/.env (root-only, mode 600) by a small
# Python helper, and are never printed, never put in command lines and never stored in shell history.
# Only the last 4 characters of a key are ever shown back to you.
set -euo pipefail

REPO_SSH="git@github.com:himanshugoel23/friday.git"
APP_DIR="/opt/friday"
ENV_FILE="/etc/friday/.env"
KEY_FILE="$HOME/.ssh/friday_deploy"
DEFAULT_BRANCH="claude/friday-phase-1"
MODE="test"; FORCE=0; BRANCH=""

say()  { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '  [ OK ] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*" >&2; }
die()  { printf '\nSTOPPED: %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- env file helper
# One small Python program does every read/write of the env file (as root, via sudo). Values arrive
# on STDIN (never in the command line); only key NAMES are passed as arguments.
read -r -d '' ENVPY <<'PY' || true
import os, re, sys, tempfile
path, op, key = os.environ.get("FRIDAY_ENV_PATH", "/etc/friday/.env"), sys.argv[1], sys.argv[2]
SECRETISH = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PEPPER)", re.I)
line_re = re.compile(r"^" + re.escape(key) + r"=(.*)$")

def parse(rest):
    rest = rest.rstrip("\r\n")
    if rest[:1] in ("'", '"'):
        q = rest[0]
        end = rest.find(q, 1)
        return (rest[1:end] if end > 0 else rest[1:]), ""
    m = re.search(r"\s+#.*$", rest)
    return (rest[:m.start()] if m else rest).strip(), (m.group(0) if m else "")

def lines():
    with open(path, encoding="utf-8") as f:
        return f.read().split("\n")

def current():
    val = None
    for ln in lines():
        m = line_re.match(ln)
        if m:
            val = parse(m.group(1))[0]
    return val

if op == "has":                      # exit 0 when set to a real value
    v = current()
    sys.exit(0 if v and "CHANGE_ME" not in v else 1)
if op == "get":                      # never prints secrets
    if SECRETISH.search(key):
        sys.exit("refusing to print a secret")
    v = current()
    print("" if v is None else v)
    sys.exit(0)
if op == "last4":
    v = current() or ""
    print(v[-4:] if len(v) >= 8 else "")
    sys.exit(0)
if op == "placeholders":             # names (only) of settings still holding CHANGE_ME
    for ln in lines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", ln)
        if m and "CHANGE_ME" in parse(m.group(2))[0]:
            print(m.group(1))
    sys.exit(0)
if op != "set":
    sys.exit("unknown op")

value = sys.stdin.read()
if "\n" in value or "\r" in value or "\x00" in value:
    sys.exit("value contains a line break; refusing")
risky = (value != value.strip() or "$" in value or re.search(r"\s#", value)
         or value[:1] in ("'", '"') or value.startswith("#"))
if risky:                            # single quotes keep docker compose and python-dotenv literal
    if "'" in value:
        sys.exit("value mixes special characters and a single quote; cannot store it safely")
    value = "'" + value + "'"
out, done = [], False
for ln in lines():
    m = line_re.match(ln)
    if m and not done:
        comment = parse(m.group(1))[1]
        out.append(f"{key}={value}{comment}")
        done = True
    elif m:
        continue                     # drop duplicates of the same key
    else:
        out.append(ln)
if not done:
    while out and out[-1] == "":
        out.pop()
    out.append(f"{key}={value}")
    out.append("")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env.")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY

envp()      { sudo env FRIDAY_ENV_PATH="$ENV_FILE" python3 -I -c "$ENVPY" "$@"; }
env_has()   { envp has "$1" </dev/null >/dev/null 2>&1; }
env_get()   { envp get "$1" </dev/null; }
env_last4() { envp last4 "$1" </dev/null; }
env_set()   { printf '%s' "$2" | envp set "$1"; }              # env_set NAME VALUE (value goes via a pipe)
env_gen()   { env_has "$1" || openssl rand -hex "$2" | tr -d '\n' | envp set "$1"; }   # env_gen NAME BYTES

# --------------------------------------------------------------------------- prompts
need_tty() { [[ -t 0 ]] || die "this script asks questions, so it must run in a terminal (not piped)."; }

# ask VAR "question" [default]  (visible input)
ask() {
  local __v="$1" q="$2" def="${3:-}" ans
  if [[ -n "$def" ]]; then read -r -p "$q [$def]: " ans; ans="${ans:-$def}"; else read -r -p "$q: " ans; fi
  printf -v "$__v" '%s' "$ans"
}
yesno() {  # yesno "question" default(Y|N)
  local q="$1" def="${2:-Y}" a
  read -r -p "$q [$def]: " a; a="${a:-$def}"; [[ "$a" =~ ^[Yy] ]]
}
# ask_secret ENVNAME "label": hidden input. Enter keeps an existing value / skips. Echoes last 4 only.
# Sets global SECRET_SET=1 when a new value was stored.
ask_secret() {
  local name="$1" label="$2" v v2 have=0
  SECRET_SET=0
  env_has "$name" && have=1
  while true; do
    if [[ $have -eq 1 ]]; then
      read -r -s -p "$label (hidden; ends ...$(env_last4 "$name"); Enter keeps it): " v
    else
      read -r -s -p "$label (hidden; paste, then Enter; Enter alone skips): " v
    fi
    echo
    v="${v//[$' \t\r\n']/}"; v="${v#[\'\"]}"; v="${v%[\'\"]}"
    [[ -n "$v" ]] || return 0
    if [[ ${#v} -lt 8 ]]; then warn "that looks too short to be a key (${#v} characters). Try again."; continue; fi
    if yesno "    Got a value ending in ...${v: -4} (${#v} characters). Correct?" Y; then
      env_set "$name" "$v"; SECRET_SET=1; unset v v2; return 0
    fi
  done
}
# ask_plain ENVNAME "label" [default]: visible value, saved to the env file; Enter keeps current/default.
ask_plain() {
  local name="$1" label="$2" def="${3:-}" cur ans
  cur="$(env_get "$name" 2>/dev/null || true)"
  [[ "$cur" == *CHANGE_ME* ]] && cur=""
  def="${cur:-$def}"
  ask ans "$label" "$def"
  [[ -n "$ans" ]] || { warn "$name left empty"; return 0; }
  env_set "$name" "$ans"
}
normalize_phone() {  # prints +E.164 or nothing
  local p="${1//[ -]/}"
  if [[ "$p" =~ ^[6-9][0-9]{9}$ ]]; then p="+91$p"; elif [[ "$p" =~ ^91[6-9][0-9]{9}$ ]]; then p="+$p"; fi
  [[ "$p" =~ ^\+[1-9][0-9]{7,14}$ ]] && printf '%s' "$p"
}

# --------------------------------------------------------------------------- steps
step_checks() {
  say "1/7  Checking the server is ready"
  [[ $EUID -ne 0 ]] || die "run this as the normal 'ubuntu' user, without sudo (it uses sudo itself where needed)."
  [[ -f /var/log/friday-bootstrap.done ]] || die "the server's first-boot setup has not finished (no /var/log/friday-bootstrap.done).
    Wait 3-5 minutes after creating the server, then run this again. To see progress: tail -n 20 /var/log/friday-bootstrap.log"
  ok "first-boot setup finished: $(cat /var/log/friday-bootstrap.done)"
  sudo docker info >/dev/null 2>&1 || die "Docker is not working. Try: sudo systemctl start docker, then run this again."
  sudo docker compose version >/dev/null 2>&1 || die "Docker Compose is missing (docker-compose-plugin)."
  ok "Docker works"
  command -v openssl >/dev/null && command -v python3 >/dev/null && command -v git >/dev/null \
    || die "openssl, python3 and git must be installed (sudo apt-get -y install openssl python3 git)."
  sudo -n true 2>/dev/null || die "sudo needs a password here; this script expects the default Lightsail 'ubuntu' user."
}

step_deploy_key_and_code() {
  say "2/7  Getting the Friday code (read-only GitHub deploy key)"
  mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
  if [[ ! -f "$KEY_FILE" ]]; then
    ssh-keygen -q -t ed25519 -N "" -f "$KEY_FILE" -C "friday-server-deploy"
    ok "created a new deploy key"
  else
    ok "deploy key already exists"
  fi
  grep -qs 'friday_deploy' "$HOME/.ssh/config" 2>/dev/null \
    || printf 'Host github.com\n  IdentityFile %s\n  IdentitiesOnly yes\n  StrictHostKeyChecking accept-new\n' "$KEY_FILE" >> "$HOME/.ssh/config"
  chmod 600 "$HOME/.ssh/config"

  if ! github_ok; then
    cat <<EOF

    GitHub does not know this server yet. Do this once (on the iPad, in another tab):
      1. Open github.com and go to the repository  himanshugoel23/friday
      2. Tap  Settings  ->  Deploy keys  ->  Add deploy key
      3. Title:  friday-test-server
      4. Key:    copy the whole line between the dashed lines below and paste it
      5. Leave "Allow write access" UNTICKED (read-only)
      6. Tap  Add key

    ------------------------------ PUBLIC key (safe to copy) ------------------------------
EOF
    cat "$KEY_FILE.pub"
    echo "    ---------------------------------------------------------------------------------------"
    while true; do
      read -r -p "    When you have added the key, press Enter to test it (or type q to quit): " a
      [[ "$a" != "q" ]] || die "stopped. Run this script again after adding the key."
      if github_ok; then break; fi
      warn "GitHub still refuses this key. Check you pasted the full line and chose the right repository."
    done
  fi
  ok "GitHub accepts the deploy key"

  if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" diff --quiet && git -C "$APP_DIR" diff --cached --quiet \
      || die "there are local changes in $APP_DIR; ask your engineer (or: cd $APP_DIR && git stash)."
    git -C "$APP_DIR" fetch --quiet origin
    git -C "$APP_DIR" checkout --quiet "$BRANCH" 2>/dev/null || git -C "$APP_DIR" checkout --quiet -b "$BRANCH" --track "origin/$BRANCH"
    git -C "$APP_DIR" pull --ff-only --quiet
    ok "code updated to branch $BRANCH ($(git -C "$APP_DIR" rev-parse --short HEAD))"
  else
    sudo install -d -o "$USER" -g "$USER" "$APP_DIR"
    [[ -z "$(ls -A "$APP_DIR" 2>/dev/null)" ]] || die "$APP_DIR is not empty and is not a git checkout; move it away first."
    git clone --quiet --branch "$BRANCH" "$REPO_SSH" "$APP_DIR"
    ok "code cloned to $APP_DIR (branch $BRANCH, $(git -C "$APP_DIR" rev-parse --short HEAD))"
  fi
  [[ -f "$APP_DIR/deploy/env.production.example" ]] || die "deploy/env.production.example not found on branch $BRANCH."
}
github_ok() {  # GitHub answers "successfully authenticated" (exit code 1) when the key is accepted
  local out; out="$(ssh -T -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new git@github.com 2>&1 || true)"
  [[ "$out" == *"successfully authenticated"* ]]
}

step_env_file() {
  say "3/7  Your secret settings file ($ENV_FILE)"
  sudo install -d -m 750 /etc/friday
  if sudo test -e "$ENV_FILE"; then
    if [[ $FORCE -eq 1 ]]; then
      warn "--force: this replaces ALL settings with a fresh template, including generated keys."
      warn "If the server already holds real data, FRIDAY_FIELD_KEY in the old file is the only way to read it."
      local a; read -r -p "    Type REPLACE to continue: " a
      [[ "$a" == "REPLACE" ]] || die "left the existing file untouched."
      local bak="$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
      sudo cp -p "$ENV_FILE" "$bak"; sudo chmod 600 "$bak"
      ok "old file saved as $bak (root-only)"
      sudo install -m 600 -o root -g root "$APP_DIR/deploy/env.production.example" "$ENV_FILE"
      ok "fresh template installed"
    else
      ok "already exists, keeping it (add --force to start over; a backup is made first)"
      local bak="$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
      sudo cp -p "$ENV_FILE" "$bak"; sudo chmod 600 "$bak"
      info "safety copy before today's edits: $bak"
    fi
  else
    sudo install -m 600 -o root -g root "$APP_DIR/deploy/env.production.example" "$ENV_FILE"
    ok "created from deploy/env.production.example"
  fi
  sudo chown root:root "$ENV_FILE"; sudo chmod 600 "$ENV_FILE"
  # random secrets (only where still a placeholder; same sizes as docs/DEPLOY_AWS.md step 8)
  local k
  for k in FRIDAY_SECRET_KEY FRIDAY_PIN_PEPPER FRIDAY_INDEX_KEY FRIDAY_FIELD_KEY FRIDAY_ADMIN_TOKEN; do env_gen "$k" 32; done
  for k in POSTGRES_PASSWORD REDIS_PASSWORD; do env_gen "$k" 24; done
  env_gen WHATSAPP_VERIFY_TOKEN 16
  ok "random secrets are in place (not shown). Back them up later: sudo cat $ENV_FILE  (see the guide)"
}

public_ip() {
  local ip="" url
  ip="$(curl -fsS --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
  if [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    for url in https://api.ipify.org https://checkip.amazonaws.com https://ifconfig.me/ip; do
      ip="$(curl -fsS --max-time 6 "$url" 2>/dev/null | tr -d '[:space:]' || true)"
      [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break || ip=""
    done
  fi
  printf '%s' "$ip"
}

step_settings_test() {
  say "4/7  Test-server settings"
  env_set FRIDAY_MODE live
  env_set FRIDAY_PROFILE pilot
  env_set FRIDAY_TELEPHONY_PROVIDER sarvam
  ok "mode=live, profile=pilot (voice-only test; WhatsApp, SMS and hotels stay simulated)"

  local ip name
  ip="$(public_ip)"
  if [[ -n "$ip" ]]; then
    echo "    This server's public IP address looks like: $ip"
    info "(If you attached a Lightsail static IP, this must be that static IP.)"
    yesno "    Is that right?" Y || ip=""
  fi
  while [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; do ask ip "    Type the server's public IPv4 address"; done
  name="${ip//./-}.sslip.io"
  env_set FRIDAY_DOMAIN "$name"
  env_set FRIDAY_PUBLIC_BASE_URL "https://$name"
  ok "free HTTPS address: https://$name  (sslip.io turns the IP into a name; no domain purchase needed)"
  info "If you later change the IP address, run this script again."

  local def_email; def_email="$(env_get ACME_EMAIL 2>/dev/null || true)"; [[ "$def_email" == *example.com* || "$def_email" == *CHANGE_ME* ]] && def_email=""
  local email
  while true; do
    ask email "    Your email address (Let's Encrypt sends certificate warnings here)" "$def_email"
    [[ "$email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] && break
    warn "that does not look like an email address."
  done
  env_set ACME_EMAIL "$email"

  # caller ID
  local cid; cid="$(env_get SARVAM_CALLER_IDS 2>/dev/null || true)"; 
  echo
  echo "    Calls are placed FROM your own Vobiz number (no default is assumed)."
  if [[ -z "$cid" ]] || ! yesno "    Use $cid as the caller ID?" Y; then
    while true; do ask cid "    Type the Vobiz number you own (like +918012345678)"; cid="$(normalize_phone "$cid" || true)"; [[ -n "$cid" ]] && break; warn "not a valid number."; done
  fi
  env_set SARVAM_CALLER_IDS "$cid"; env_set FRIDAY_NUMBERS "$cid"
  ok "caller ID: $cid"

  # allowed test number(s): the ONLY numbers Friday may ever dial from this server
  local cur allowed raw n list
  cur="$(env_get FRIDAY_PILOT_ALLOWED_NUMBERS 2>/dev/null || true)"
  echo
  echo "    SAFETY: Friday will only ever call the number(s) you list here. Type YOUR OWN mobile number."
  while true; do
    ask raw "    Your mobile number (10 digits or +91...; several: separate with commas)" "$cur"
    list=""; allowed=1
    IFS=',' read -r -a parts <<<"$raw"
    for n in "${parts[@]}"; do
      n="$(normalize_phone "$n" || true)"
      if [[ -z "$n" ]]; then allowed=0; break; fi
      list="${list:+$list,}$n"
    done
    [[ $allowed -eq 1 && -n "$list" ]] || { warn "please type a valid mobile number."; continue; }
    yesno "    Friday may call: $list . Correct?" Y && break
  done
  env_set FRIDAY_PILOT_ALLOWED_NUMBERS "$list"

  # unused production settings must not stay as CHANGE_ME (update.sh refuses placeholders)
  local k
  for k in GOOGLE_PLACES_API_KEY WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_APP_SECRET \
           FRIDAY_TERMS_URL FRIDAY_PRIVACY_URL FRIDAY_GRIEVANCE_EMAIL; do
    env_has "$k" || env_set "$k" ""
  done
  env_has FRIDAY_ADMIN_PHONES || env_set FRIDAY_ADMIN_PHONES "[]"
}

step_settings_prod() {
  say "4/7  Private-beta production settings (beta profile)"
  env_set FRIDAY_MODE live
  env_set FRIDAY_PROFILE beta
  env_set FRIDAY_TELEPHONY_PROVIDER sarvam
  echo "    Your domain's DNS A record must already point at this server's static IP (docs/DEPLOY_AWS.md step 4)."
  local dom
  while true; do
    ask dom "    Your domain (like friday.yourcompany.in, no https://)" "$(env_get FRIDAY_DOMAIN 2>/dev/null | grep -v -e 'example.com' -e CHANGE_ME || true)"
    dom="${dom#https://}"; dom="${dom%/}"
    [[ "$dom" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] && break
    warn "that does not look like a domain name."
  done
  env_set FRIDAY_DOMAIN "$dom"; env_set FRIDAY_PUBLIC_BASE_URL "https://$dom"
  local email
  while true; do
    ask email "    Your email address (Let's Encrypt notices)" "$(env_get ACME_EMAIL 2>/dev/null | grep -v -e 'example.com' -e CHANGE_ME || true)"
    [[ "$email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] && break
    warn "that does not look like an email address."
  done
  env_set ACME_EMAIL "$email"

  local n
  while true; do
    ask n "    Your dedicated Vobiz number(s), comma separated (not the trial number)" "$(env_get FRIDAY_NUMBERS 2>/dev/null | grep -v CHANGE_ME || true)"
    local ok_all=1 list="" p; IFS=',' read -r -a ps <<<"$n"
    for p in "${ps[@]}"; do p="$(normalize_phone "$p" || true)"; [[ -n "$p" ]] || { ok_all=0; break; }; list="${list:+$list,}$p"; done
    [[ $ok_all -eq 1 && -n "$list" ]] && break
    warn "please type valid numbers."
  done
  env_set FRIDAY_NUMBERS "$list"; env_set SARVAM_CALLER_IDS ""

  local admin
  while true; do
    ask admin "    Your own WhatsApp number (skips the invite step)"; admin="$(normalize_phone "$admin" || true)"
    [[ -n "$admin" ]] && break; warn "not a valid number."
  done
  env_set FRIDAY_ADMIN_PHONES "[\"$admin\"]"

  ask_plain FRIDAY_TERMS_URL "    Terms of service URL (https://...)"
  ask_plain FRIDAY_PRIVACY_URL "    Privacy policy URL (https://...)"
  ask_plain FRIDAY_GRIEVANCE_EMAIL "    Grievance Officer email"
  ask_secret GOOGLE_PLACES_API_KEY "    Google Places/Geocoding API key"
  ask_secret WHATSAPP_ACCESS_TOKEN "    WhatsApp permanent access token"
  ask_plain WHATSAPP_PHONE_NUMBER_ID "    WhatsApp phone number ID"
  ask_secret WHATSAPP_APP_SECRET "    WhatsApp app secret"
}

step_keys() {
  say "5/7  API keys (hidden typing: nothing appears on screen while you paste)"
  echo "    Press Enter on any question to skip a key that is already saved."
  local had_openai=0 had_anthropic=0 new_o=0 new_a=0 choice=""
  env_has OPENAI_API_KEY && had_openai=1
  env_has ANTHROPIC_API_KEY && had_anthropic=1
  echo
  echo "    The AI brain: one key is enough (OpenAI or Anthropic)."
  ask_secret OPENAI_API_KEY "    OpenAI API key (sk-...)"; new_o=$SECRET_SET
  ask_secret ANTHROPIC_API_KEY "    Anthropic API key (sk-ant-...)"; new_a=$SECRET_SET
  local have_o=0 have_a=0
  env_has OPENAI_API_KEY && have_o=1
  env_has ANTHROPIC_API_KEY && have_a=1
  [[ $have_o -eq 1 || $have_a -eq 1 ]] || die "no AI key yet: run this again and paste an OpenAI or Anthropic key."
  if [[ $have_o -eq 1 && $have_a -eq 1 ]]; then
    local cur; cur="$(env_get FRIDAY_LLM_PROVIDER 2>/dev/null || true)"
    if [[ "$cur" != openai && "$cur" != anthropic || $new_o -eq 1 || $new_a -eq 1 ]]; then
      ask choice "    You have both. Which should Friday use? (openai / anthropic)" "${cur:-openai}"
      [[ "$choice" == openai || "$choice" == anthropic ]] || die "type exactly openai or anthropic."
    else choice="$cur"; fi
  elif [[ $have_o -eq 1 ]]; then choice=openai; else choice=anthropic; fi
  env_set FRIDAY_LLM_PROVIDER "$choice"
  # an unused Anthropic placeholder would block update.sh
  env_has ANTHROPIC_API_KEY || env_set ANTHROPIC_API_KEY ""
  ok "AI brain: $choice"
  : "$had_openai$had_anthropic"

  ask_secret SARVAM_API_KEY "    Sarvam API key"
  env_has SARVAM_API_KEY || die "the Sarvam key is required (speech). Run this again with the key."
  local id; id="$(env_get SARVAM_TELEPHONY_AUTH_ID 2>/dev/null || true)"; [[ "$id" == *CHANGE_ME* ]] && id=""
  ask id "    Vobiz Auth ID (visible; from the Vobiz console)" "$id"
  [[ -n "$id" ]] || die "the Vobiz Auth ID is required."
  env_set SARVAM_TELEPHONY_AUTH_ID "$id"
  ok "Vobiz Auth ID saved (ends ...${id: -4})"
  ask_secret SARVAM_TELEPHONY_AUTH_TOKEN "    Vobiz Auth Secret"
  env_has SARVAM_TELEPHONY_AUTH_TOKEN || die "the Vobiz Auth Secret is required."
}

step_validate() {
  say "6/7  Final check of the settings file"
  local left; left="$(envp placeholders x </dev/null || true)"
  if [[ -n "$left" ]]; then
    warn "these settings still say CHANGE_ME (names only):"
    printf '      %s\n' $left >&2
    die "fill them (run this script again) or ask your engineer; nothing was started."
  fi
  ok "no placeholders left; file is root-only: $(sudo stat -c '%U:%G %a' "$ENV_FILE")"
}

step_start() {
  say "7/7  Building and starting Friday (first time takes 5-10 minutes; leave the screen on)"
  cd "$APP_DIR"
  if [[ "$MODE" == test ]]; then
    # test server: no S3 backup configured, nobody to wait for on a re-run, and git was already pulled by us
    sudo ./deploy/update.sh --no-pull --fast --skip-backup
  else
    sudo ./deploy/update.sh --no-pull
  fi
}

summary() {
  local dom; dom="$(env_get FRIDAY_DOMAIN)"
  say "All done"
  if [[ "$MODE" == test ]]; then
    cat <<EOF
    Friday TEST server is running.
      Health page : https://$dom/health      (should show {"status":"ok"} with a padlock)
      Place a test call to your phone:
          bash $APP_DIR/deploy/livecall.sh --to <your number, e.g. +919812345678>
      It asks you to type YES, rings your phone, and prints a short summary when the call ends.
      Watch the logs  : sudo $APP_DIR/deploy/dc.sh logs -f --tail=100 api     (Ctrl+C to leave)
      Is it healthy   : sudo $APP_DIR/deploy/smoke_test.sh
      Stop everything : sudo $APP_DIR/deploy/dc.sh stop      (start again: sudo $APP_DIR/deploy/dc.sh up -d)
      New code later  : bash $APP_DIR/deploy/first-run.sh    (safe to repeat; keeps your answers)
    Reminder: this is a TEST server. Use test data only, never real customers' information.
    When finished testing: stop the server in Lightsail (see docs/DEPLOY_TEST_SERVER.md).
EOF
  else
    cat <<EOF
    Friday (private beta, beta profile) is running at https://$dom
    Next: docs/DEPLOY_AWS.md steps 10-12 (register the Vobiz and WhatsApp webhooks, backups), then
    docs/PRODUCTION_CHECKLIST.md before you resume from pause. New code later: bash $APP_DIR/deploy/first-run.sh --prod
EOF
  fi
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --test) MODE=test ;;
      --prod) MODE=prod ;;
      --force) FORCE=1 ;;
      -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; return 0 ;;
      -*) die "unknown option $1" ;;
      *) BRANCH="$1" ;;
    esac
    shift
  done
  BRANCH="${BRANCH:-$DEFAULT_BRANCH}"
  need_tty
  echo "Friday first-run setup: $([[ $MODE == test ]] && echo 'TEST server (pilot profile)' || echo 'PRODUCTION (beta profile)'), branch $BRANCH"
  echo "Nothing secret is shown on screen. You can stop with Ctrl+C and run this again at any time."
  step_checks
  step_deploy_key_and_code
  step_env_file
  if [[ "$MODE" == test ]]; then step_settings_test; else step_settings_prod; fi
  step_keys
  step_validate
  step_start
  summary
}

# keep this on ONE line: bash must not read the rest of the file after git replaces it mid-run
main "$@"; exit $?
