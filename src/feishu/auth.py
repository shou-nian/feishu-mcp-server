"""飞书自建应用 tenant_access_token 管理。"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from src.feishu.errors import FeishuAuthError

TENANT_ACCESS_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"


@dataclass(frozen=True, slots=True)
class CachedToken:
    """带本地过期时间的 tenant_access_token。"""

    value: str
    expires_at: float


class FeishuAuth:
    """并发安全的 tenant_access_token 获取与缓存。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        app_id: str,
        app_secret: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http_client = http_client
        self._app_id = app_id
        self._app_secret = app_secret
        self._clock = clock
        self._cached_token: CachedToken | None = None
        self._refresh_lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        """返回有效 token，过期或明确要求时自动刷新。"""

        if not force_refresh and self._is_cache_valid():
            return self._cached_token.value  # type: ignore[union-attr]

        async with self._refresh_lock:
            if not force_refresh and self._is_cache_valid():
                return self._cached_token.value  # type: ignore[union-attr]
            self._cached_token = await self._fetch_token()
            return self._cached_token.value

    def invalidate(self) -> None:
        """使缓存 token 立即失效。"""

        self._cached_token = None

    def _is_cache_valid(self) -> bool:
        return self._cached_token is not None and self._clock() < self._cached_token.expires_at

    async def _fetch_token(self) -> CachedToken:
        try:
            response = await self._http_client.post(
                TENANT_ACCESS_TOKEN_PATH,
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
        except httpx.HTTPError as exc:
            raise FeishuAuthError("无法连接飞书鉴权服务，请稍后重试") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise FeishuAuthError("飞书鉴权服务返回了无法解析的响应") from exc

        if response.is_error or payload.get("code", -1) != 0:
            raise FeishuAuthError("飞书鉴权失败，请检查 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        token = payload.get("tenant_access_token")
        expires_in = payload.get("expire", 0)
        if not isinstance(token, str) or not token or not isinstance(expires_in, (int, float)):
            raise FeishuAuthError("飞书鉴权响应缺少 tenant_access_token 或有效期")

        # 提前刷新可避免请求发出时 token 恰好过期；短有效期 token 也至少保留一半时长。
        refresh_buffer = min(60.0, max(1.0, float(expires_in) * 0.1))
        usable_lifetime = max(float(expires_in) - refresh_buffer, float(expires_in) * 0.5)
        return CachedToken(value=token, expires_at=self._clock() + usable_lifetime)
