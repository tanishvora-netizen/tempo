"""Small protections for a public, no-auth demo: security headers and a per-IP throttle on live solves."""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

LIVE_SOLVES_PER_MINUTE = 6
WINDOW_S = 60.0
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


class SecurityHeaders(BaseHTTPMiddleware):
    """Everything is self-hosted (vendored assets), so the CSP allows only this origin."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response


class Throttle:
    """At most `limit` CPU-heavy requests per client IP per rolling minute (the host has 0.1 CPU)."""

    def __init__(self, limit: int = LIVE_SOLVES_PER_MINUTE, window_s: float = WINDOW_S) -> None:
        self.limit = limit
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self.hits[ip]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(
                status_code=429, detail="Too many live re-solves; try a preset or wait a minute."
            )
        q.append(now)
