import time

import httpx
import pytest

from legal_engine.core.exceptions import RobotsDisallowedError
from legal_engine.ingestion.rate_limiter import PoliteFetcher, RateLimiter, RobotsCache

pytestmark = pytest.mark.asyncio


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRobotsCache:
    async def test_allows_when_robots_txt_permits(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        assert await cache.is_allowed("https://example.gov/code/section-1") is True
        await client.aclose()

    async def test_disallows_blocked_path(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        assert await cache.is_allowed("https://example.gov/private/x") is False
        assert await cache.is_allowed("https://example.gov/public/x") is True
        await client.aclose()

    async def test_missing_robots_txt_is_unrestricted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        assert await cache.is_allowed("https://example.gov/anything") is True
        await client.aclose()

    async def test_server_error_fetching_robots_txt_fails_closed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        assert await cache.is_allowed("https://example.gov/anything") is False
        await client.aclose()

    async def test_network_error_fetching_robots_txt_fails_closed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        assert await cache.is_allowed("https://example.gov/anything") is False
        await client.aclose()

    async def test_robots_txt_fetched_once_per_host(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")

        client = _client(handler)
        cache = RobotsCache(client, user_agent="legal-engine-bot/0.1")
        await cache.is_allowed("https://example.gov/a")
        await cache.is_allowed("https://example.gov/b")
        assert calls == ["https://example.gov/robots.txt"]
        await client.aclose()


class TestRateLimiter:
    async def test_enforces_minimum_delay_between_requests_to_same_host(self):
        limiter = RateLimiter(min_delay_seconds=0.1, max_concurrency=5)

        start = time.monotonic()
        async with limiter.throttle("example.gov"):
            pass
        async with limiter.throttle("example.gov"):
            pass
        elapsed = time.monotonic() - start

        assert elapsed >= 0.1

    async def test_different_hosts_are_not_throttled_against_each_other(self):
        limiter = RateLimiter(min_delay_seconds=1.0, max_concurrency=5)

        start = time.monotonic()
        async with limiter.throttle("a.gov"):
            pass
        async with limiter.throttle("b.gov"):
            pass
        elapsed = time.monotonic() - start

        assert elapsed < 0.5  # nowhere near the 1s per-host delay


class TestPoliteFetcher:
    async def test_fetch_raises_when_robots_disallows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /blocked/\n")
            return httpx.Response(200, text="ok")

        client = _client(handler)
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, max_concurrency=5)
        with pytest.raises(RobotsDisallowedError):
            await fetcher.fetch("https://example.gov/blocked/x")
        await fetcher.aclose()

    async def test_fetch_retries_on_429_honoring_retry_after(self):
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            attempts.append(1)
            if len(attempts) < 2:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, text="finally succeeded")

        client = _client(handler)
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, max_concurrency=5)
        response = await fetcher.fetch("https://example.gov/x")
        assert response.text == "finally succeeded"
        assert len(attempts) == 2
        await fetcher.aclose()

    async def test_fetch_gives_up_after_max_retries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\n")
            return httpx.Response(503, headers={"Retry-After": "0"})

        client = _client(handler)
        fetcher = PoliteFetcher(client=client, min_delay_seconds=0, max_concurrency=5, max_retries=1)
        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch("https://example.gov/x")
        await fetcher.aclose()

    async def test_fetch_succeeds_when_robots_txt_disabled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok")

        client = _client(handler)
        fetcher = PoliteFetcher(
            client=client, min_delay_seconds=0, max_concurrency=5, respect_robots_txt=False
        )
        response = await fetcher.fetch("https://example.gov/anything")
        assert response.text == "ok"
        await fetcher.aclose()
