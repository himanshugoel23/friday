# ruff: noqa: E501
"""Product images: ONLY from cited product pages (their og:image) or an image URL the provider itself
cited. Nothing else is ever shown or fetched. Fails soft: no image means a text-only card."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Protocol
from urllib.parse import urljoin, urlparse

from friday.core.logging import get_logger

log = get_logger(__name__)
_OG = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image(?::secure_url)?|twitter:image)[\"'][^>]*>", re.I
)
_CONTENT = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)
MAX_BYTES = 300_000


class ImagePort(Protocol):
    async def image_for(self, page_url: str) -> str | None: ...


class NoImages:
    async def image_for(self, page_url: str) -> str | None:  # noqa: ARG002
        return None


class FakeImages:
    """Tests: ``mapping`` is page url -> image url; calls are recorded; no network."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping, self.calls = mapping or {}, []

    async def image_for(self, page_url: str) -> str | None:
        self.calls.append(page_url)
        return self.mapping.get(page_url)


def public_https(url: str | None) -> bool:
    """https only, with a host that is not a literal private/loopback address."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname or u.hostname == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(u.hostname)
    except ValueError:
        return "." in u.hostname
    return ip.is_global


def og_image_from_html(html: str, base_url: str) -> str | None:
    for tag in _OG.findall(html or ""):
        m = _CONTENT.search(tag)
        if m:
            img = urljoin(base_url, m.group(1).strip())
            if public_https(img):
                return img
    return None


async def _resolves_public(host: str) -> bool:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


class HttpOgImages:
    """Fetches a CITED product page (never anything else) and reads its og:image. Short timeout, size
    capped, no redirects, https and public hosts only. Not exercised against the real web in tests."""

    def __init__(self, *, timeout_s: float = 4.0) -> None:
        self.timeout_s = timeout_s

    async def image_for(self, page_url: str) -> str | None:
        import httpx

        if not public_https(page_url) or not await _resolves_public(urlparse(page_url).hostname or ""):
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False) as c, c.stream(
                "GET", page_url, headers={"User-Agent": "Mozilla/5.0 (compatible; FridayBot)", "Range": f"bytes=0-{MAX_BYTES}"}
            ) as r:
                if r.status_code >= 400:
                    return None
                buf = b""
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) >= MAX_BYTES:
                        break
        except Exception as e:  # noqa: BLE001 - images are a nicety
            log.info("product image: fetch failed %s", type(e).__name__)
            return None
        return og_image_from_html(buf.decode("utf-8", "ignore"), page_url)
