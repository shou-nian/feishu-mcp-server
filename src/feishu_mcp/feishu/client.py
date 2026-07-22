"""统一的飞书开放平台异步 HTTP Client。"""

from typing import Any

import httpx

from feishu_mcp.config.settings import Settings
from feishu_mcp.feishu.auth import FeishuAuth
from feishu_mcp.feishu.errors import FeishuAPIError

AUTH_ERROR_CODES = {99991661, 99991663, 99991664, 99991668}
ERROR_MESSAGES = {
    99991663: "飞书鉴权失败，请检查 FEISHU_APP_ID 和 FEISHU_APP_SECRET",
    99991664: "飞书应用已停用，请检查应用状态",
    99991668: "飞书访问凭证已过期，请重试",
    91403: "飞书应用缺少文档权限，请在开放平台配置所需权限",
    1770032: "飞书文档不存在，或当前应用无权访问",
}


class FeishuClient:
    """自动添加鉴权、刷新 token 并校验业务错误码的客户端。"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str = "https://open.feishu.cn",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )
        self.auth = FeishuAuth(self._http_client, app_id, app_secret)

    @classmethod
    def from_settings(cls, settings: Settings) -> "FeishuClient":
        """从应用配置创建客户端。"""

        return cls(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_url=settings.feishu_base_url,
            timeout=settings.feishu_request_timeout,
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """调用飞书 API，成功时返回响应中的 data 对象。"""

        request_headers = dict(kwargs.pop("headers", {}))
        for attempt in range(2):
            token = await self.auth.get_token(force_refresh=attempt > 0)
            headers = dict(request_headers)
            headers["Authorization"] = f"Bearer {token}"

            try:
                response = await self._http_client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise FeishuAPIError("无法连接飞书开放平台，请稍后重试") from exc

            payload = self._parse_response(response)
            code = payload.get("code", 0)
            if attempt == 0 and (response.status_code == 401 or code in AUTH_ERROR_CODES):
                self.auth.invalidate()
                continue

            if response.is_error or code != 0:
                raise self._to_api_error(response.status_code, code, payload.get("msg"))

            data = payload.get("data", {})
            return data if isinstance(data, dict) else {"value": data}

        raise FeishuAPIError("飞书访问凭证刷新后仍不可用，请检查应用配置")

    async def aclose(self) -> None:
        """关闭由当前实例创建的连接池。"""

        if self._owns_http_client:
            await self._http_client.aclose()

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {"code": 0, "data": {}}
        try:
            payload = response.json()
        except ValueError as exc:
            raise FeishuAPIError(
                f"飞书开放平台返回了无法解析的响应（HTTP {response.status_code}）"
            ) from exc
        if not isinstance(payload, dict):
            raise FeishuAPIError("飞书开放平台返回了非对象响应")
        return payload

    @staticmethod
    def _to_api_error(status_code: int, code: Any, message: Any) -> FeishuAPIError:
        numeric_code = code if isinstance(code, int) else None
        friendly = ERROR_MESSAGES.get(numeric_code)
        if friendly is None:
            details = str(message) if message else "未知错误"
            friendly = f"飞书 API 调用失败（code={code}, HTTP {status_code}）：{details}"
        return FeishuAPIError(friendly, code=numeric_code)
