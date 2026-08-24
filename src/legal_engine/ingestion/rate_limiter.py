"""Polite crawling policy: robots.txt compliance, per-host rate limiting, and
respectful retry/backoff.

Deliberate deviation from the original spec's anti_blocking.py (JA3/JA4 TLS
fingerprint impersonation + jitter to evade WAF rate-limiting): this module
implements honest, well-behaved crawling instead —

- robots.txt is fetched and checked before any other request to a host
- a truthful, identifying User-Agent (see settings.ingestion_user_agent)
- bounded global concurrency (settings.ingestion_max_concurrency)
- a minimum delay between requests to the *same* host
  (settings.ingestion_min_delay_seconds)
- exponential backoff on 429/503, honoring any Retry-After header

Public government/legal-statute sources are the ingestion target, so
there's no legitimate need for fingerprint spoofing or anti-detection
tooling here — being a good, identifiable citizen crawler is both simpler
and the right call.
"""

from __future__ import annotations

import asyncio
import email.utils
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Self
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from legal_engine.core.config import settings
from legal_engine.core.exceptions import RobotsDisallowedError


class RobotsCache:
    """Fetches and caches robots.txt per host, then answers can-fetch checks.

    robots.txt itself is fetched through the same httpx client (so it goes
    through the same mocking/transport in tests, and isn't a special case
    the rest of the fetch path has to reason about).
    """

    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._guard = asyncio.Lock()

    async def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        parser = await self._get_parser(parsed.scheme, parsed.netloc)
        return parser.can_fetch(self._user_agent, url)

    async def _get_parser(self, scheme: str, host: str) -> RobotFileParser:
        async with self._guard:
            if host in self._parsers:
                return self._parsers[host]

            parser = RobotFileParser()
            robots_url = f"{scheme}://{host}/robots.txt"
            try:
                response = await self._client.get(robots_url, timeout=10.0)
            except httpx.HTTPError:
                # Can't confirm what's allowed: fail closed rather than crawl blind.
                parser.parse(["User-agent: *", "Disallow: /"])
                self._parsers[host] = parser
                return parser

            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            elif response.status_code in (404, 410):
                parser.parse([])  # confirmed absent: unrestricted
            else:
                # Ambiguous (403/5xx/etc): the file might exist and be
                # restrictive but temporarily unreachable — fail closed.
                parser.parse(["User-agent: *", "Disallow: /"])

            self._parsers[host] = parser
            return parser


class RateLimiter:
    """Bounded global concurrency plus a minimum per-host delay between requests."""

    def __init__(self, min_delay_seconds: float, max_concurrency: int) -> None:
        self._min_delay = min_delay_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._last_request_at: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_locks_guard = asyncio.Lock()

    @asynccontextmanager
    async def throttle(self, host: str) -> AsyncIterator[None]:
        async with self._semaphore:
            host_lock = await self._lock_for_host(host)
            async with host_lock:
                last = self._last_request_at.get(host)
                if last is not None:
                    remaining = self._min_delay - (time.monotonic() - last)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                self._last_request_at[host] = time.monotonic()
            yield

    async def _lock_for_host(self, host: str) -> asyncio.Lock:
        async with self._host_locks_guard:
            if host not in self._host_locks:
                self._host_locks[host] = asyncio.Lock()
            return self._host_locks[host]


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        if retry_after.isdigit():
            return float(retry_after)
        try:
            target = email.utils.parsedate_to_datetime(retry_after)
        except (TypeError, ValueError):
            target = None
        if target is not None:
            return max((target - datetime.now(UTC)).total_seconds(), 0.0)
    return float(2**attempt)


class PoliteFetcher:
    """Wires RobotsCache + RateLimiter + retry/backoff around an httpx.AsyncClient."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        user_agent: str = settings.ingestion_user_agent,
        min_delay_seconds: float = settings.ingestion_min_delay_seconds,
        max_concurrency: int = settings.ingestion_max_concurrency,
        respect_robots_txt: bool = settings.ingestion_respect_robots_txt,
        max_retries: int = 3,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(headers={"User-Agent": user_agent})
        self._robots = RobotsCache(self._client, user_agent)
        self._rate_limiter = RateLimiter(min_delay_seconds, max_concurrency)
        self._respect_robots_txt = respect_robots_txt
        self._max_retries = max_retries

    async def fetch(self, url: str) -> httpx.Response:
        if self._respect_robots_txt and not await self._robots.is_allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

        host = urlparse(url).netloc
        attempt = 0
        while True:
            async with self._rate_limiter.throttle(host):
                response = await self._client.get(url)

            if response.status_code not in (429, 503):
                return response

            attempt += 1
            if attempt > self._max_retries:
                response.raise_for_status()

            await asyncio.sleep(_retry_delay(response, attempt))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
