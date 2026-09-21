import hashlib
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.memory: dict[str, deque[float]] = defaultdict(deque)
        self.redis = None
        if not settings.mock_external_services:
            try:
                from redis.asyncio import from_url
                self.redis = from_url(settings.redis_url, socket_connect_timeout=0.2, decode_responses=True)
            except Exception:
                self.redis = None

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(settings.api_prefix):
            return await call_next(request)
        path = request.url.path
        sensitive = path.endswith("/auth/wechat") or path.endswith("/auth/login") or path.endswith("/auth/register") or path.endswith("/admin/auth/login")
        limit = 20 if sensitive else 120
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
        auth = request.headers.get("authorization", "anonymous")
        identity = hashlib.sha256(f"{ip}:{auth}".encode()).hexdigest()[:24]
        bucket = int(time.time() // 60)
        key = f"rate:{identity}:{bucket}"
        count = await self._increment(key)
        if count > limit:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"},
                                headers={"Retry-After": "60"})
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

    async def _increment(self, key: str) -> int:
        if self.redis:
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.incr(key)
                    pipe.expire(key, 70)
                    result = await pipe.execute()
                    return int(result[0])
            except Exception:
                pass
        now = time.time()
        queue = self.memory[key]
        while queue and now - queue[0] > 70:
            queue.popleft()
        queue.append(now)
        if len(self.memory) > 10000:
            self.memory.clear()
        return len(queue)

