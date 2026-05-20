"""Small async wrapper around cachetools TTLCache."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from cachetools import TTLCache

from app.config import settings

T = TypeVar("T")


class AsyncTTLCache:
    """A process-local TTL cache guarded by an asyncio lock."""

    def __init__(self, maxsize: int = 512, ttl: int = settings.cache_ttl_seconds) -> None:
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()

    async def get_or_set(self, key: str, factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Return a cached value or compute and store it."""

        async with self._lock:
            if key in self._cache:
                return self._cache[key]
        value = await factory()
        async with self._lock:
            self._cache[key] = value
        return value

    async def clear(self) -> None:
        """Remove all cached entries."""

        async with self._lock:
            self._cache.clear()


cache = AsyncTTLCache()

