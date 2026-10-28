# Self-updating small server

Goal (founder, 2026-10-28): stop pasting update commands in the console.

- `deploy/install-autoupdate.sh` is run ONCE as root. It adds a systemd timer (every 3 minutes) that runs `deploy/autoupdate.sh`.
- `autoupdate.sh`: if origin/claude/friday-phase-1 has new commits: fast-forward pull, `uv sync`, migrate, restart, health + doctor. A fixed sequence; it runs no other scripts.
- It writes `var/autoupdate/status.txt` (no secrets). `GET /ops-status/<token>` serves it read-only (`friday/api/opsstatus.py`); the token is `FRIDAY_OPS_STATUS_TOKEN` in the server `.env`. Off when unset.
- Limits: it cannot change `.env` keys or run one-off commands. Those still need the console (hidden-prompt scripts) or a future approved mechanism. The DigitalOcean connector can reboot/resize/snapshot but has no run-command tool; SSH from the build sandbox is blocked.
- A "run any pushed script as root" mechanism was considered and NOT built (auto mode classifier denied it; it would give anyone with push access root on the server). Ask the founder before adding it.
