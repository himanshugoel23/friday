"""FRIDAY_BROWSER_* settings (own class: core/config.py belongs to another team; wire it in later).

Everything defaults to OFF / safest. ``FRIDAY_BROWSER_ENABLED=true`` alone enables nobody: testers
are named in ``FRIDAY_BROWSER_ENABLED_USERS`` (comma separated user ids, or ``*`` for all).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRIDAY_BROWSER_", env_file=None, extra="ignore", case_sensitive=False)

    enabled: bool = False
    enabled_users: str = ""
    backend: str = "local"  # local | cloud | fake
    cloud_provider: str = ""
    headed: bool = False  # headed Chromium (needs a display, see display)
    display: str = ":99"  # virtual display for headed mode (Xvfb)
    resolve_dns: bool = True  # block listed names that resolve to private addresses
    timeout_ms: int = 8000
    task_max_seconds: float = 600.0
    max_pages: int = 3
    max_downloads: int = 0
    max_per_user: int = 1
    max_global: int = 3
    vault_ttl_days: int = 30
    vault_dir: str = "var/browser_vault"
    # website PASSWORD vault (docs/CREDENTIAL_VAULT.md): off unless the user is named
    credentials_enabled: bool = False
    credentials_enabled_users: str = ""  # comma user ids, or * (empty enables nobody)
    credentials_ttl_days: int = 90
    credentials_dir: str = "var/browser_credentials"
    credentials_link_ttl_seconds: float = 600.0
    live_link_ttl_seconds: float = 900.0  # a watch link must be opened within this time
    live_view_ttl_seconds: float = 900.0  # after opening, the view lasts this long
    frame_min_interval_ms: int = 400
    takeover_max_seconds: float = 300.0

    def user_allowed(self, user_id: str) -> bool:
        if not self.enabled:
            return False
        names = {n.strip() for n in self.enabled_users.split(",") if n.strip()}
        return "*" in names or user_id in names

    def credentials_allowed(self, user_id: str) -> bool:
        if not (self.enabled and self.credentials_enabled):
            return False
        names = {n.strip() for n in self.credentials_enabled_users.split(",") if n.strip()}
        return "*" in names or user_id in names
