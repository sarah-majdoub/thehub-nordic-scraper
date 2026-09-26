"""A polite, retrying async HTTP client."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import Settings

log = logging.getLogger(__name__)


class RetryableStatus(Exception):
    """Raised for statuses that are worth trying again (429, 5xx)."""


class HubClient:
    """Wraps httpx with HTTP/2, a concurrency gate, and backoff on retryable errors."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._gate = asyncio.Semaphore(settings.concurrency)
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=settings.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/json",
            },
            limits=httpx.Limits(max_connections=settings.concurrency * 2),
        )

    async def __aenter__(self) -> "HubClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        async with self._gate:
            data = await self._get_json(url, params)
            # Spacing requests inside the gate keeps the *sustained* rate low
            # rather than just capping how many run at once.
            await asyncio.sleep(self.settings.delay)
            return data

    async def _get_json(self, url: str, params: dict[str, Any] | None) -> Any:
        @retry(
            retry=retry_if_exception_type((RetryableStatus, httpx.TransportError)),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(self.settings.max_retries),
            reraise=True,
        )
        async def attempt() -> Any:
            r = await self._client.get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                raise RetryableStatus(f"{r.status_code} for {r.request.url}")
            r.raise_for_status()
            return r.json()

        return await attempt()
