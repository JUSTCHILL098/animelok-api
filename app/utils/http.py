"""HTTP client utilities."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx
from fake_useragent import UserAgent

from app.config import settings
from app.utils.exceptions import ScraperError

logger = logging.getLogger(__name__)


class HttpClient:
    """Shared async HTTP client with browser headers and retry logic."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Create the underlying AsyncClient."""

        if self._client is not None:
            return
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout),
            follow_redirects=True,
            headers=self.default_headers(),
        )

    async def close(self) -> None:
        """Close the underlying AsyncClient."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def default_headers(referer: str | None = None) -> dict[str, str]:
        """Return headers that look like a normal browser request."""

        try:
            user_agent = UserAgent().chrome
        except Exception:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    async def get_text(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> str:
        """GET a URL and return text."""

        response = await self.get(url, headers=headers, params=params)
        return response.text

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """GET a URL and return parsed JSON."""

        response = await self.get(url, headers=headers, params=params)
        return response.json()

    async def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        """POST form data and return parsed JSON."""

        response = await self.post(url, headers=headers, data=data, json=json)
        return response.json()

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """GET with retries and useful errors."""

        await self.start()
        assert self._client is not None
        merged_headers = dict(self._client.headers)
        if headers:
            merged_headers.update(headers)

        last_error: Exception | None = None
        for attempt in range(1, settings.request_retries + 1):
            try:
                response = await self._client.get(url, headers=merged_headers, params=params)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning("GET failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt < settings.request_retries:
                    await asyncio.sleep(0.35 * attempt)
        raise ScraperError(f"Failed to fetch {url}: {last_error}") from last_error

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """POST with retries and useful errors."""

        await self.start()
        assert self._client is not None
        merged_headers = dict(self._client.headers)
        if headers:
            merged_headers.update(headers)

        last_error: Exception | None = None
        for attempt in range(1, settings.request_retries + 1):
            try:
                response = await self._client.post(url, headers=merged_headers, data=data, json=json)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning("POST failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt < settings.request_retries:
                    await asyncio.sleep(0.35 * attempt)
        raise ScraperError(f"Failed to post {url}: {last_error}") from last_error


http_client = HttpClient()
