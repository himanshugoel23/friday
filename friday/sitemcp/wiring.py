# ruff: noqa: E501
"""Build the site MCP hub and the shopping providers from Settings. Nothing starts a browser here: Chromium launches lazily on
the first real tool call (or probe run). OFF unless FRIDAY_SITE_MCP_ENABLED."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.shopping.sites import GroceryProvider, WebGroceryProvider
from friday.sitemcp.chromium import SharedChromium
from friday.sitemcp.guard import MemoryGuard, RobotsPolicy
from friday.sitemcp.hub import SiteMcpHub
from friday.sitemcp.knowledge import load_knowledge
from friday.sitemcp.probestore import ProbeStore
from friday.sitemcp.provider import BrowserMcpGroceryProvider, FallbackGroceryProvider
from friday.sitemcp.runtime import BrowserFactory, SessionPool
from friday.sitemcp.site import SiteServer

_HUBS: dict[int, SiteMcpHub] = {}


def store_for(settings: Any) -> ProbeStore:
    return ProbeStore(Path(getattr(settings, "site_mcp_dir", "var/sitemcp")))


def enabled_sites(settings: Any) -> list[str]:
    kbs = load_knowledge()
    return [s for s in getattr(settings, "site_mcp_sites", []) if s in kbs]


def build_hub(settings: Any, *, browser_stack: Any = None, factory: BrowserFactory | None = None) -> SiteMcpHub:
    """One hub per Settings object (the pool, caps and the single shared Chromium are process wide)."""
    hub = _HUBS.get(id(settings))
    if hub is not None and factory is None:
        return hub
    from friday.connectors.session.vault import FileVaultStore, StorageVault, cipher_from_settings

    root = Path(getattr(settings, "site_mcp_dir", "var/sitemcp"))
    vault = StorageVault(FileVaultStore(root / "vault"), cipher_from_settings(settings))  # cookies encrypted per user, erasable
    pool = SessionPool(factory or SharedChromium(), vault=vault, robots=RobotsPolicy(),
                       memory=MemoryGuard(float(getattr(settings, "site_mcp_min_free_mb", 250))),
                       max_sessions=int(getattr(settings, "site_mcp_max_sessions", 2)), idle_s=float(getattr(settings, "site_mcp_idle_s", 240)))
    otp = tokens = None
    base = str(getattr(settings, "public_base_url", "") or "").rstrip("/")
    on_started = None
    if browser_stack is not None:  # reuse the existing secure OTP page and the guarded login-OTP flow
        otp, tokens = browser_stack.otp, browser_stack.otp_tokens
        pending = getattr(browser_stack, "pending_logins", None)
        if pending is not None:
            on_started = pending.expect
    kbs = load_knowledge()
    servers = {s: SiteServer(kbs[s], pool, otp=otp, tokens=tokens, otp_url=lambda t: f"{base}/connectors/otp/{t}", on_login_started=on_started)
               for s in enabled_sites(settings)}
    hub = SiteMcpHub(servers, pool)
    _HUBS[id(settings)] = hub
    return hub


def shopping_overrides(settings: Any, web_provider: Any, *, browser_stack: Any = None, timeout_s: float = 20.0,
                       now: Any = None) -> dict[str, GroceryProvider]:
    """site -> browser-first provider with the web provider as the fallback. Empty unless the switch is on."""
    if not getattr(settings, "site_mcp_enabled", False):
        return {}
    from friday.shopping.sites import load_knowledge as load_shop_kb

    hub = build_hub(settings, browser_stack=browser_stack)
    shop = load_shop_kb()
    out: dict[str, GroceryProvider] = {}
    for site in hub.sites():
        if site not in shop:
            continue
        web = WebGroceryProvider(shop[site], web_provider, timeout_s=min(20.0, timeout_s), now=now)
        out[site] = FallbackGroceryProvider(BrowserMcpGroceryProvider(hub, shop[site], now=now), web)
    return out
