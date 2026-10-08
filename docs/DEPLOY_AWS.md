# Deploying Friday (private beta) on AWS Mumbai: step by step

For: the founder, no engineering background needed. Time: about half a day the first time.
Goal: Friday running on ONE small server in India (AWS region **ap-south-1, Mumbai**), reachable at
your own domain over HTTPS, with nightly encrypted backups, a kill switch and a rollback.

Everything the server runs is in this repo: `Dockerfile`, `deploy/` (the stack, the web server
config, backup, update and test scripts). Nothing secret is ever stored in the repo.

> **The golden rules**
> 1. Secrets (API keys, tokens, passwords) are typed **only** into `/etc/friday/.env` on the server.
>    Never in chat, email, WhatsApp, screenshots, tickets or git.
> 2. If a secret was ever pasted somewhere else, treat it as leaked and create a fresh one.
> 3. When in doubt, pause Friday (section 13, "Kill switch") first, think second.
> 4. AWS and vendor screens change often. If a button has a slightly different name, look for the
>    nearest match. Prices below are **estimates**; confirm current prices before you commit.

---

## 0. What you will have at the end

```
Internet --(80/443)--> Caddy (HTTPS, certificates)
                          |
                          v
                         api  = Friday web + task engine + phone calls   (one process, on purpose)
                         worker-proactive = nudges / morning briefings
                          |                    |
                       Postgres 16          Redis      <- not reachable from the internet
                          |
        nightly dump --> S3 bucket in Mumbai (encrypted, auto-deleted after 30 days)
```

Why one process runs the web, task and voice parts: during a phone call, the call itself, the audio
stream from Vobiz and the question Friday asks you on WhatsApp mid-call all live in the memory of
the **same** process. Splitting them across containers breaks mid-call questions. That is fine for a
beta and is the main thing to redesign when you scale (section 15).

**Hard limit for now:** live-call state, the Vobiz media WebSocket and mid-call questions are held in
memory, so the `voice`, `task` and `api` roles must run in **ONE process per VM** (the compose `split`
profile is disabled). Do not run two `api` containers or add a second VM behind a load balancer: a
call's audio and its mid-call question would land in different processes and fail. A restart cuts live calls.

---

## 1. Create the AWS account safely (30 min)

1. Go to <https://aws.amazon.com> and choose **Create an AWS account**. Use a company email address
   that several people can read (for example `aws@yourcompany.in`), not a personal one. Pick a strong
   unique password and store it in a password manager.
2. Add a payment card and complete identity verification. Choose the **Basic (free) support plan**.
   In India your bill is issued by Amazon Web Services India (AISPL) and 18% GST is added.
3. **Lock the root user with MFA** (the root user is the all-powerful login that you will almost never use):
   sign in as root -> top-right account name -> **Security credentials** -> **Multi-factor authentication (MFA)**
   -> **Assign MFA device** -> *Authenticator app* -> scan the QR code with an authenticator app on your
   phone -> enter two consecutive codes. Save the recovery information offline.
4. **Create an everyday admin user** (do not work as root):
   - Search for **IAM** in the top search bar -> **Users** -> **Create user**; name `friday-admin`;
     tick *Provide user access to the AWS Management Console* -> *I want to create an IAM user* ->
     set a password.
   - **Permissions** -> *Attach policies directly* -> tick `AdministratorAccess` (acceptable for the
     founder's own admin user, because it is protected by MFA).
   - Create it, then open the user -> **Security credentials** -> **Assign MFA device** (same as step 3).
   - Note the **sign-in URL** shown on the IAM dashboard (`https://<account-id>.signin.aws.amazon.com/console`).
     From now on sign in with that URL as `friday-admin`. Sign out of root.
5. **Let the admin user see billing**: sign in as *root* once -> account name -> **Account** -> scroll to
   *IAM user and role access to Billing information* -> **Edit** -> **Activate IAM Access** -> Update.
6. **Set a budget alert** (so a mistake cannot become a surprise bill): as `friday-admin` search
   **Billing and Cost Management** -> **Budgets** -> **Create budget** -> *Use a template* ->
   **Monthly cost budget**; budget amount **USD 60** (adjust to taste); put your email in the
   notification list. It alerts at 85% actual, 100% actual and 100% forecast. Also tick
   **Billing preferences -> Receive billing alerts** and **Receive PDF invoice**.

## 2. Choose the region (1 min)

Top-right corner of the console: choose **Asia Pacific (Mumbai) ap-south-1**. Do this every time you
sign in; the Lightsail and S3 screens only show what is in the selected region. Keeping data in
India is also a launch requirement (docs/SECURITY_FIXES.md OPS-1).

## 3. Create the server (Lightsail) (15 min)

1. Search **Lightsail** -> open it -> **Create instance**.
2. *Instance location*: confirm it says **Mumbai, Zone A (ap-south-1a)**.
3. *Pick your instance image*: **Linux/Unix** -> **OS Only** -> **Ubuntu 24.04 LTS**.
4. *SSH key pair*: create a new key pair named `friday-prod` and **download the .pem file**. Keep it
   safe; whoever holds it can log in. (Windows: use Windows Terminal / PowerShell `ssh`, it is built in.)
5. *Enable automatic snapshots*: on, at a quiet time such as 03:00 IST.
6. *Choose your instance plan*: **4 GB RAM / 2 vCPU / 80 GB SSD** (about USD 24 a month). 2 GB is too
   small for Postgres + the app + the image build.
7. *Name*: `friday-prod`. **Create instance**. Wait until it says *Running*.

### 3a. Static IP and firewall

1. Instance -> **Networking** tab -> **Create static IP** -> attach to `friday-prod` -> name `friday-ip`
   -> Create. Write down this IP address (it stays yours as long as it is attached).
2. Same tab, **IPv4 Firewall** rules. You want exactly:

   | Application | Protocol | Port | Restricted to |
   |---|---|---|---|
   | SSH | TCP | 22 | **only your IP** (tick *Restrict to IP address*, add your office/home IP) and *Lightsail browser SSH/RDP* |
   | HTTP | TCP | 80 | any |
   | HTTPS | TCP | 443 | any |
   | Custom | UDP | 443 | any (optional, for HTTP/3) |

   Delete every other rule. If your home IP changes you can still log in with the orange
   **Connect using SSH** button in the Lightsail console (that is why that box is ticked).
3. **IPv6 Firewall** rules tab: apply the same restrictions (or turn IPv6 networking off for the instance).
4. Postgres (5432) and Redis (6379) must **never** appear in these rules. The stack does not publish
   them to the host at all; the firewall is a second lock.

## 4. Point your domain at the server (10 min + waiting)

At the website where you bought your domain (GoDaddy, Namecheap, BigRock, etc.) open DNS settings and add:

| Type | Name / Host | Value | TTL |
|---|---|---|---|
| A | `friday` (gives `friday.yourdomain.com`) | the static IP from step 3a | 300 |

Check from your computer (may take a few minutes): `nslookup friday.yourdomain.com` must show your IP.
**Do not start Friday before this works**: the HTTPS certificate is requested automatically on first start.

## 5. Log in to the server and prepare it (15 min)

On your computer (replace the IP and the path to the downloaded key):

```bash
ssh -i /path/to/friday-prod.pem ubuntu@<STATIC-IP>
```
(Windows: if ssh complains about key permissions, right-click the .pem -> Properties -> Security so only you can read it. Or use the Lightsail *Connect using SSH* button.)

On the server:

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get -y install git unzip curl python3 unattended-upgrades
sudo timedatectl set-timezone Asia/Kolkata
# a 2 GB swap file so a busy moment cannot crash the server
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo reboot     # then log in again after a minute
```

## 6. Install Docker (5 min)

```bash
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker run --rm hello-world       # should print "Hello from Docker!"
```

## 7. Copy the Friday code onto the server (10 min)

The repository is private, so the server needs a read-only "deploy key":

```bash
sudo mkdir -p /opt/friday && sudo chown ubuntu:ubuntu /opt/friday
ssh-keygen -t ed25519 -N "" -f ~/.ssh/friday_deploy -C "friday-prod-deploy"
cat ~/.ssh/friday_deploy.pub          # copy this single line (it is a PUBLIC key, safe to copy)
```
On GitHub: the repository -> **Settings** -> **Deploy keys** -> **Add deploy key** -> paste, title
`friday-prod`, leave *Allow write access* **unticked** -> Add key. Back on the server:

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/friday_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
git clone git@github.com:himanshugoel23/friday.git /opt/friday
cd /opt/friday && git checkout <the-branch-your-engineer-names>   # e.g. main, once it is merged
```

## 8. Create the server's secret file (20 min, the important one)

All secrets live in **one file** that only root can read: `/etc/friday/.env`.

```bash
cd /opt/friday
sudo install -d -m 750 /etc/friday
sudo cp deploy/env.production.example /etc/friday/.env
sudo chmod 600 /etc/friday/.env

# 1) generate the random secrets directly into the file (the values are never shown on screen)
for k in FRIDAY_SECRET_KEY FRIDAY_PIN_PEPPER FRIDAY_INDEX_KEY FRIDAY_FIELD_KEY FRIDAY_ADMIN_TOKEN; do
  sudo sed -i "s|^$k=.*|$k=$(openssl rand -hex 32)|" /etc/friday/.env
done
for k in POSTGRES_PASSWORD REDIS_PASSWORD; do
  sudo sed -i "s|^$k=.*|$k=$(openssl rand -hex 24)|" /etc/friday/.env
done
sudo sed -i "s|^WHATSAPP_VERIFY_TOKEN=.*|WHATSAPP_VERIFY_TOKEN=$(openssl rand -hex 16)|" /etc/friday/.env

# 2) type the rest by hand
sudo nano /etc/friday/.env
```
In `nano`: move with the arrow keys; **right-click or Shift+Insert pastes** what you copied from each vendor's
console (paste only into the terminal, never anywhere else); `Ctrl+O` Enter saves; `Ctrl+X` exits.
Fill every `CHANGE_ME`:

| Name | Where it comes from |
|---|---|
| `FRIDAY_DOMAIN`, `FRIDAY_PUBLIC_BASE_URL`, `ACME_EMAIL` | your domain from step 4 (`https://`, no slash at the end) |
| `FRIDAY_ADMIN_PHONES` | your own WhatsApp number as `["+91XXXXXXXXXX"]` |
| `ANTHROPIC_API_KEY` | console.anthropic.com -> API keys (a **new** key; set a monthly spend limit there) |
| `SARVAM_API_KEY` | Sarvam dashboard (new key) |
| `SARVAM_TELEPHONY_AUTH_ID`, `SARVAM_TELEPHONY_AUTH_TOKEN` | Vobiz console (these names are historical: it is the Vobiz Auth ID / Secret) |
| `FRIDAY_NUMBERS` | your dedicated Vobiz number(s), e.g. `+9180XXXXXXXX` |
| `GOOGLE_PLACES_API_KEY` | Google Cloud -> APIs & Services -> Credentials (enable *Places API (New)* and *Geocoding API*; restrict the key to the server IP; set a budget) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` | Meta developers -> your app -> WhatsApp (use a permanent System User token) |

Leave the "OPTIONAL" section empty to keep hotels, SMS and call recordings **off**. Off means disabled, never simulated: hotel tasks use the direct-call path only (users are told live rates are not available), SMS is skipped (WhatsApp or a call-back is used), and `friday check` lists each disabled feature. Also set `FRIDAY_TERMS_URL`, `FRIDAY_PRIVACY_URL` and `FRIDAY_GRIEVANCE_EMAIL` (required).

**Back up the keys.** Print the file once to a screen you control, copy it into your password manager
as a secure note, and close the screen: `sudo cat /etc/friday/.env`. In particular `FRIDAY_FIELD_KEY`:
**if it is lost, the encrypted database cannot be read, even from a backup.**

## 9. Start Friday (15 min)

```bash
cd /opt/friday
sudo ./deploy/update.sh
```
This builds the image (a few minutes), checks your settings (`friday check`; it lists by name anything
missing), creates the database tables, starts everything and runs the smoke test. When it ends with
`DONE: <version> is live` and `SMOKE TEST PASSED` you are up. If it stops, read the last lines: they
name exactly what is wrong. Fix `/etc/friday/.env` and re-run the same command; it is safe to repeat.

Useful commands (always from `/opt/friday`):

```bash
sudo ./deploy/dc.sh ps                          # what is running
sudo ./deploy/dc.sh logs -f --tail=100 api      # live logs (Ctrl+C to leave; phone numbers are masked)
sudo ./deploy/smoke_test.sh                     # re-run the health checks any time
```
Open `https://friday.yourdomain.com/health` in a browser: it must show `{"status":"ok"}` with a padlock.

## 10. Register the webhook URLs (20 min)

First make sure Friday is **paused** while you wire things up:
`sudo ./deploy/dc.sh exec api friday pause` (you will resume in step 11).

### 10a. Vobiz (phone calls)
Friday gives Vobiz a fresh URL for each call it places, so you only register the URLs for **calls
coming in** to your Friday number (a business calling back). First print the secret URL token (it is
derived from your `FRIDAY_SECRET_KEY`, treat it like a password):

```bash
sudo ./deploy/dc.sh exec api python -c "import os;from friday.voice.telephony.sarvam import sarvam_token as t;print(t(os.environ['FRIDAY_SECRET_KEY'],'inbound'))"
```
In the Vobiz console -> your Voice Application for the Friday number:

| Field | Value |
|---|---|
| Answer URL | `https://friday.yourdomain.com/voice/sarvam/inbound?token=<TOKEN>` (method POST) |
| Hangup URL | `https://friday.yourdomain.com/voice/sarvam/hangup?token=<TOKEN>` |
| Media stream | nothing to enter: Friday's answer reply tells Vobiz to open `wss://friday.yourdomain.com/voice/sarvam/media?...` itself, and Caddy passes the WebSocket through |
| Call queuing | **OFF** |
| Account | upgraded from trial; balance topped up |

Without the correct token the server answers 403; that is intended.

### 10b. Meta WhatsApp
developers.facebook.com -> your app -> **WhatsApp** -> **Configuration** -> Webhook -> **Edit**:

| Field | Value |
|---|---|
| Callback URL | `https://friday.yourdomain.com/webhooks/whatsapp` |
| Verify token | exactly the `WHATSAPP_VERIFY_TOKEN` in `/etc/friday/.env` (read it with `sudo grep ^WHATSAPP_VERIFY_TOKEN /etc/friday/.env`) |

Click **Verify and save**, then under *Webhook fields* **subscribe to `messages`**. Meta calls the URL
with your token (Friday answers only if it matches) and afterwards signs every message with your app secret;
unsigned or wrongly signed requests are rejected (the smoke test proves this).

## 11. Run the smoke test and the first message (15 min)

```bash
sudo ./deploy/smoke_test.sh
```
Every line must say `[ OK ]` (a `[WARN]` that the kill switch is ON is expected right now). It checks:
containers healthy, HTTPS and the padlock header, `/admin/health` refuses strangers, database migrations are
current, forged WhatsApp and Vobiz requests are rejected, only ports 80/443 are open, and
`friday check --live` (it reads your Vobiz balance and numbers; it **never** places a call).

Then docs/PRODUCTION_CHECKLIST.md decides whether you may proceed. When the checklist's gate is green (and the backups of step 12 are working):
`sudo ./deploy/dc.sh exec api friday pause --resume`, and message the Friday WhatsApp number from your phone.

## 12. Backups to S3 (20 min)

1. **Bucket**: search **S3** -> region Mumbai -> **Create bucket**; name `friday-backups-<yourname>-mumbai`;
   *Block all public access*: on (default); *Bucket versioning*: on; *Default encryption*: SSE-S3 (default).
2. **Lifecycle** (so old backups delete themselves): bucket -> **Management** -> **Create lifecycle rule** ->
   name `expire-30d`, scope: prefix `postgres/` -> actions: *Expire current versions of objects* after **30**
   days and *Permanently delete noncurrent versions* after **7** days -> also *Delete expired object delete
   markers or incomplete multipart uploads* -> Create.
3. **A backup-only IAM user**: IAM -> **Policies** -> **Create policy** -> JSON, paste (replace the bucket name):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Sid": "WriteAndReadBackups", "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::friday-backups-YOURNAME-mumbai/postgres/*" },
       { "Sid": "ListBackups", "Effect": "Allow",
         "Action": ["s3:ListBucket"],
         "Resource": "arn:aws:s3:::friday-backups-YOURNAME-mumbai",
         "Condition": { "StringLike": { "s3:prefix": ["postgres/*"] } } }
     ]
   }
   ```
   Name it `friday-backup-minimal`. This user can add and read backups but **cannot delete or overwrite
   existing ones** (an attacker with the server cannot erase your history; deletion happens only through
   the lifecycle rule). Then **Users** -> **Create user** `friday-backup` (no console access) -> attach that policy ->
   **Security credentials** -> **Create access key** -> *Application running outside AWS* -> copy both values.
4. **On the server** install the AWS CLI and the config file:
   ```bash
   cd /tmp && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip -q awscliv2.zip && sudo ./aws/install && rm -rf aws awscliv2.zip
   sudo nano /etc/friday/backup.env      # type the 4 lines below, save
   sudo chmod 600 /etc/friday/backup.env
   ```
   ```
   BACKUP_BUCKET=friday-backups-YOURNAME-mumbai
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_DEFAULT_REGION=ap-south-1
   ```
5. Test, then schedule nightly at 01:47 IST:
   ```bash
   sudo /opt/friday/deploy/backup.sh          # must end with "backup finished"
   echo '17 20 * * * root /opt/friday/deploy/backup.sh >> /var/log/friday-backup.log 2>&1' | sudo tee /etc/cron.d/friday-backup
   ```
6. **Do the restore drill once** (`deploy/restore.md`, section A) before any real user joins. A backup you
   have never restored is only a hope.

(Recordings: off in the beta. If you later enable them, they need their own bucket and credentials for
the containers, plus the legal decisions in the checklist. Ask your engineer first.)

---

## 13. Everyday operations

### First-week monitoring (10 minutes a day)
- `sudo ./deploy/smoke_test.sh` is all green.
- `sudo ./deploy/dc.sh ps`: all `Up` / `healthy`; nothing restarting.
- Logs: `sudo ./deploy/dc.sh logs --since 24h api | grep -iE "error|exception|traceback" | head -30`.
- Admin health: dead letters must be 0 (the smoke test reads this for you).
- Read yesterday's call transcripts and costs (checklist section "Pilot rollout plan").
- Money: Vobiz balance, Anthropic usage page, Google Cloud billing, AWS Budgets email.
- Disk: `df -h /` (under 70% is healthy). Backup: the newest file in the S3 `postgres/` folder is from last night.
- Meta: WhatsApp Manager -> phone number *quality rating* is green.
- Apply security updates monthly: `sudo apt-get update && sudo apt-get -y upgrade && sudo reboot`, then run the smoke test.

### Kill switch (use it first, ask questions later)
```bash
sudo ./deploy/dc.sh exec api friday pause              # STOP all calls and nudges, within a second
sudo ./deploy/dc.sh exec api friday pause --status
sudo ./deploy/dc.sh exec api friday pause --resume
```
While paused: no outbound calls, no proactive messages, scheduled calls/retries wait in the queue;
new requests get a polite "taking a short break" reply; calls already in progress finish normally;
people can still message Friday. `FRIDAY_PAUSED=true` in `.env` keeps it paused even after restarts.
Harder stops: `sudo ./deploy/dc.sh stop api worker-proactive` (everything off), or in the Meta console
unsubscribe the webhook, or in Vobiz remove the number's application.

### Releasing a new version
```bash
cd /opt/friday && sudo ./deploy/update.sh
```
It pulls the code, builds, checks the configuration with the new image, takes a backup, pauses new calls
and waits ~5 minutes for running calls to end (`--fast` skips the wait), applies database migrations,
restarts the services one at a time, smoke-tests, and **automatically rolls back** to the previous image if the
smoke test fails. Release outside call hours.

### Rolling back by hand
```bash
sudo ./deploy/update.sh --rollback        # previous image, database untouched
```
Database changes are not reversed by this (migrations only add things, so the old version keeps working
in practice). If data is damaged, restore a backup: `deploy/restore.md` section B.

### Rotating keys
| Secret | How |
|---|---|
| Anthropic, Sarvam, Google, Meta token, Vobiz auth, `FRIDAY_ADMIN_TOKEN`, `WHATSAPP_VERIFY_TOKEN` | Create the new key at the vendor -> `sudo nano /etc/friday/.env` -> `sudo ./deploy/dc.sh up -d --force-recreate api worker-proactive` -> smoke test -> **revoke the old key** at the vendor. Verify token / admin token: also update Meta's webhook form. |
| `FRIDAY_SECRET_KEY` | Edit + recreate, then re-print the Vobiz token (step 10a) and update the Vobiz URLs (calls in flight fail once). |
| `POSTGRES_PASSWORD` | `sudo ./deploy/dc.sh exec postgres psql -U friday -c "ALTER USER friday PASSWORD 'NEWHEX'"`, edit `.env`, recreate. |
| `FRIDAY_PIN_PEPPER`, `FRIDAY_INDEX_KEY`, `FRIDAY_FIELD_KEY` | **Do not change by yourself.** Changing them locks every user's PIN or makes stored data unreadable. Ask your engineer; it needs a re-encryption step. |
| AWS backup user | IAM -> user -> create a second access key, update `backup.env`, test, delete the old key. |
| Server SSH key | Lightsail -> Account -> SSH keys; add a new one, remove the old one from `~/.ssh/authorized_keys`. |

If a key leaks: pause (kill switch), rotate that key at the vendor immediately, then update the server.

### If the server dies
Create a new instance (steps 3-7), put your saved `.env` back (step 8), start Postgres only and follow
`deploy/restore.md` section B, then `sudo ./deploy/update.sh --no-pull`. Lightsail daily snapshots are a second safety net
(Instance -> Snapshots -> *Create new instance from snapshot*).

---

## 14. Estimated monthly cost (rough; confirm current AWS prices before committing)

Assumptions: INR 85-90 per USD, 4 GB Lightsail plan, a handful of testers. AWS prices in Mumbai can be a
few percent different from US prices and change; 18% GST is added to AWS and most Indian vendor bills.

| Item | Rough monthly cost | Notes |
|---|---|---|
| Lightsail 4 GB instance (2 vCPU, 80 GB) | about USD 24 (about INR 2,100) | includes a generous data transfer allowance |
| Static IP | USD 0 while attached | charged only if left unattached |
| Lightsail automatic snapshots | about USD 4 (about INR 350) | about USD 0.05 per GB-month of snapshot data |
| S3 backups (30 days of nightly dumps) | under USD 1 | a small database makes tiny dumps |
| Domain name | about INR 70-150 | INR 800-1,800 per year, varies by registrar |
| **AWS + domain subtotal** | **about INR 2,700-3,400** | before GST add up to 18% on the AWS part |
| Anthropic (LLM) | variable | the main variable cost; set a monthly cap in their console |
| Sarvam (speech) | variable | per audio minute / character |
| Vobiz (calls) | variable + number rental | about INR 0.44 per minute streaming rate per docs/LIVE_TEST_WINDOWS.md, plus per-number rental |
| Google Maps Platform | usually small | Places and Geocoding have monthly free credit; set a budget and key restrictions |
| Meta WhatsApp | variable | user-initiated chats are cheap or free; business-initiated template messages are paid per message |

A whole call (voice + speech + AI) was estimated at roughly INR 3-5 per minute in docs/LIVE_TEST_WINDOWS.md
and INR 0.4-1.2 per simulated task in docs/QA_REPORT.md. As an illustration only: 10 testers x 15 tasks a
month x about INR 10 per task is about INR 1,500, so the infrastructure is the bigger fixed cost while the beta is small.
Real numbers will come from the daily cost review. Prices change: check the AWS Lightsail pricing page and each
vendor's pricing page before you rely on any figure here.

---

## 15. Growing up: ECS + RDS + ElastiCache (later)

Move when you have more than a few dozen active users, need zero-downtime releases, or an auditor asks for
managed databases. Plan with your engineer (this is a project of days, not hours):

| Today (one VM) | Later (AWS managed) |
|---|---|
| Postgres container | **RDS for PostgreSQL 16**, Multi-AZ, private subnets, encryption on, `sslmode=verify-full`, automated backups + PITR. Migrate with a last `pg_dump`/`pg_restore` (deploy/restore.md), then change `FRIDAY_DATABASE_URL`. |
| Redis container | **ElastiCache for Redis** (private, auth token) -> `REDIS_URL` |
| Docker image on the VM | **ECR** repository + **ECS Fargate** services (one image, roles chosen by command: `serve`, `worker --roles proactive`, `task`, `voice`) |
| Caddy | **Application/Network Load Balancer** + ACM certificate (+ **WAF**). Vobiz media WebSockets must reach the process that owns the call (the app emits `?w=<worker id>`; see docs/ARCHITECTURE.md section 10.3). Today voice+task share the `api` process; before running several voice tasks, mid-call questions must be made cross-process (engineering work). |
| `/etc/friday/.env` | **AWS Secrets Manager** + ECS task-role access; `FRIDAY_FIELD_KEY_ID` pointing at an **AWS KMS** key instead of `FRIDAY_FIELD_KEY` (OPS-1) |
| Cron `backup.sh` | RDS snapshots; S3 for recordings via the task role (no access keys) |
| Logs on the VM | **CloudWatch Logs** + alarms on 5xx, dead letters, queue depth, cost |
| Manual `update.sh` | CI/CD (GitHub Actions) building to ECR and a rolling ECS deploy; migrations as a one-off ECS task before the rollout |

The `worker-task` and `worker-voice` services in `deploy/docker-compose.prod.yml` (profile `split`) are the
starting point for that design; do not turn them on for the single VM.

**What must change before scale-out** (engineering project): (1) sticky routing by call id so a call's
media WebSocket and webhooks always reach the process that owns it (load balancer rule on the `?w=` worker id);
(2) move live-call state and mid-call questions out of process memory into shared state (Redis or Postgres:
call sessions, pending questions, answer delivery), so any process can accept the user's WhatsApp answer and
hand it to the process holding the call; (3) only then enable the `split` profile and run more than one voice worker.
