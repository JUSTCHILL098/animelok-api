"""Custom middleware."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory IP rate limiter."""

    def __init__(self, app: Callable[..., Awaitable[Response]]) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = self._hits[client]
        while bucket and now - bucket[0] > settings.rate_limit_window_seconds:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_requests:
            return ORJSONResponse(
                {"success": False, "error": "Rate limit exceeded"},
                status_code=429,
            )
        bucket.append(now)
        return await call_next(request)
