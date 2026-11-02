"""飞书用户身份 OAuth 授权与 token 生命周期管理。"""

import asyncio
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import lark_oapi as lark
from lark_oapi.core.model import RequestOption

from feishu_mcp.config.settings import Settings
from feishu_mcp.feishu.errors import FeishuAuthError
from feishu_mcp.feishu.token_store import StoredUserToken, TokenStore

AUTHORIZATION_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
REFRESH_AHEAD_SECONDS = 300
LOGIN_REQUIRED_MESSAGE = "飞书用户授权无效或已过期，请执行 `uv run feishu-mcp login` 重新授权"


class FeishuOAuthService:
    """使用官方 SDK 完成授权码换票、刷新和请求注入。"""

    def __init__(
        self,
        sdk_client: lark.Client,
        *,
        app_id: str,
        redirect_uri: str,
        scopes: list[str],
        token_store: TokenStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._sdk_client = sdk_client
        self._app_id = app_id
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._token_store = token_store
        self._clock = clock
        self._cached_token: StoredUserToken | None = None
        self._refresh_lock: asyncio.Lock | None = None

    @classmethod
    def from_settings(cls, settings: Settings, sdk_client: lark.Client) -> "FeishuOAuthService":
        """从应用配置创建 OAuth 服务。"""

        return cls(
            sdk_client,
            app_id=settings.feishu_app_id,
            redirect_uri=settings.feishu_redirect_uri,
            scopes=settings.user_scope_list,
            token_store=TokenStore(settings.feishu_token_file),
        )

    def build_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """构造用户授权 URL，并返回配套的 state。"""

        actual_state = state or secrets.token_urlsafe(24)
        query = urlencode(
            {
                "client_id": self._app_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "scope": " ".join(self._scopes),
                "state": actual_state,
            }
        )
        return f"{AUTHORIZATION_URL}?{query}", actual_state

    def exchange_authorization_code(self, code: str) -> StoredUserToken:
        """用授权码换取 token 并立即持久化。"""

        if not code.strip():
            raise FeishuAuthError("飞书授权码不能为空")
        try:
            response = self._sdk_client.access_token.retrieve_by_authorization_code(
                code,
                redirect_uri=self._redirect_uri,
                scope=" ".join(self._scopes),
            )
        except Exception as exc:
            raise FeishuAuthError("飞书用户授权失败，请重新执行 `uv run feishu-mcp login`") from exc
        token = self._token_from_response(response, previous=None)
        self._token_store.save(token)
        self._cached_token = token
        return token

    async def get_request_option(self) -> RequestOption:
        """返回带有效 user_access_token 的 SDK 请求选项。"""

        token = self._cached_token or self._token_store.load()
        if token is None:
            raise FeishuAuthError(LOGIN_REQUIRED_MESSAGE)
        self._cached_token = token

        now = int(self._clock())
        if token.access_token_expires_at > now + REFRESH_AHEAD_SECONDS:
            return _request_option(token.access_token)
        if token.refresh_token_expires_at <= now:
            raise FeishuAuthError(LOGIN_REQUIRED_MESSAGE)

        lock = self._get_refresh_lock()
        async with lock:
            current = self._cached_token or token
            now = int(self._clock())
            if current.access_token_expires_at > now + REFRESH_AHEAD_SECONDS:
                return _request_option(current.access_token)
            refreshed = await asyncio.to_thread(self._refresh_token, current)
            return _request_option(refreshed.access_token)

    def _refresh_token(self, current: StoredUserToken) -> StoredUserToken:
        try:
            response = self._sdk_client.access_token.refresh(
                current.refresh_token,
                scope=" ".join(self._scopes),
            )
        except Exception as exc:
            raise FeishuAuthError(LOGIN_REQUIRED_MESSAGE) from exc
        token = self._token_from_response(response, previous=current)
        self._token_store.save(token)
        self._cached_token = token
        return token

    def _token_from_response(
        self,
        response: Any,
        *,
        previous: StoredUserToken | None,
    ) -> StoredUserToken:
        access_token = getattr(response, "access_token", None)
        refresh_token = getattr(response, "refresh_token", None)
        expires_in = getattr(response, "expires_in", None)
        refresh_expires_in = getattr(response, "refresh_token_expires_in", None)

        if not isinstance(access_token, str) or not access_token:
            raise FeishuAuthError("飞书 OAuth 响应缺少 access_token，请重新授权")
        if previous is not None and (not isinstance(refresh_token, str) or not refresh_token):
            refresh_token = previous.refresh_token
        if not isinstance(refresh_token, str) or not refresh_token:
            raise FeishuAuthError(
                "飞书 OAuth 响应缺少 refresh_token，请确认已申请 offline_access 权限"
            )
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise FeishuAuthError("飞书 OAuth 响应缺少有效的 access_token 有效期")

        now = int(self._clock())
        if isinstance(refresh_expires_in, int) and refresh_expires_in > 0:
            refresh_expires_at = now + refresh_expires_in
        elif previous is not None:
            refresh_expires_at = previous.refresh_token_expires_at
        else:
            raise FeishuAuthError(
                "飞书 OAuth 响应缺少有效的 refresh_token 有效期，请确认已申请 offline_access 权限"
            )

        scope = getattr(response, "scope", None)
        return StoredUserToken(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=now + expires_in,
            refresh_token_expires_at=refresh_expires_at,
            scope=scope if isinstance(scope, str) else "",
        )

    def _get_refresh_lock(self) -> asyncio.Lock:
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self._refresh_lock


def _request_option(access_token: str) -> RequestOption:
    return RequestOption.builder().user_access_token(access_token).build()
