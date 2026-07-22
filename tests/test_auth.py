"""飞书 tenant_access_token 的纯 Mock 测试。"""

import asyncio

import httpx
import pytest

from src.feishu.auth import FeishuAuth
from src.feishu.errors import FeishuAuthError


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_get_token_and_use_cache() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path.endswith("/tenant_access_token/internal")
        return httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "token-1", "expire": 7200},
        )

    async def scenario() -> tuple[str, str]:
        async with httpx.AsyncClient(
            base_url="https://open.feishu.cn",
            transport=httpx.MockTransport(handler),
        ) as client:
            auth = FeishuAuth(client, "cli_test", "secret")
            return await auth.get_token(), await auth.get_token()

    first, second = asyncio.run(scenario())
    assert first == second == "token-1"
    assert calls == 1


def test_expired_token_is_refreshed() -> None:
    calls = 0
    clock = Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": f"token-{calls}", "expire": 10},
        )

    async def scenario() -> tuple[str, str]:
        async with httpx.AsyncClient(
            base_url="https://open.feishu.cn",
            transport=httpx.MockTransport(handler),
        ) as client:
            auth = FeishuAuth(client, "cli_test", "secret", clock=clock)
            first = await auth.get_token()
            clock.now += 10
            second = await auth.get_token()
            return first, second

    assert asyncio.run(scenario()) == ("token-1", "token-2")
    assert calls == 2


def test_auth_error_is_user_friendly() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 99991663, "msg": "invalid app secret"})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://open.feishu.cn",
            transport=httpx.MockTransport(handler),
        ) as client:
            await FeishuAuth(client, "bad", "bad").get_token()

    with pytest.raises(FeishuAuthError, match="请检查 FEISHU_APP_ID"):
        asyncio.run(scenario())
