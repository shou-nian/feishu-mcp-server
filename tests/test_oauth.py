"""飞书 OAuth 授权与 token 刷新的纯 Mock 测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from feishu_mcp.feishu.errors import FeishuAuthError
from feishu_mcp.feishu.oauth import FeishuOAuthService
from feishu_mcp.feishu.token_store import StoredUserToken, TokenStore


class FakeAccessToken:
    def __init__(self, *, exchange: object | None = None, refresh: object | None = None) -> None:
        self.exchange = exchange
        self.refresh_response = refresh
        self.exchange_calls: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, object]] = []

    def retrieve_by_authorization_code(
        self,
        code: str,
        *,
        redirect_uri: str | None = None,
        scope: str | None = None,
    ) -> object:
        self.exchange_calls.append({"code": code, "redirect_uri": redirect_uri, "scope": scope})
        if isinstance(self.exchange, Exception):
            raise self.exchange
        return self.exchange

    def refresh(self, refresh_token: str, *, scope: str | None = None) -> object:
        self.refresh_calls.append({"refresh_token": refresh_token, "scope": scope})
        if isinstance(self.refresh_response, Exception):
            raise self.refresh_response
        return self.refresh_response


class FakeClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> float:
        return float(self.value)


def _service(
    access_token: FakeAccessToken,
    store: TokenStore,
    clock: FakeClock,
) -> FeishuOAuthService:
    client = SimpleNamespace(access_token=access_token)
    return FeishuOAuthService(  # type: ignore[arg-type]
        client,
        app_id="cli_test",
        redirect_uri="http://127.0.0.1:8765/callback",
        scopes=["docx:document", "wiki:wiki", "offline_access"],
        token_store=store,
        clock=clock,
    )


def test_authorization_url_contains_encoded_scope_and_state(tmp_path: Path) -> None:
    service = _service(FakeAccessToken(), TokenStore(tmp_path / "tokens.json"), FakeClock(100))

    url, state = service.build_authorization_url("known-state")
    query = parse_qs(urlsplit(url).query)

    assert state == "known-state"
    assert query["client_id"] == ["cli_test"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8765/callback"]
    assert query["scope"] == ["docx:document wiki:wiki offline_access"]
    assert query["state"] == ["known-state"]


def test_exchange_code_saves_token(tmp_path: Path) -> None:
    access_token = FakeAccessToken(
        exchange=SimpleNamespace(
            access_token="u-access",
            refresh_token="ur-refresh",
            expires_in=7200,
            refresh_token_expires_in=2_592_000,
            scope="docx:document offline_access",
        )
    )
    store = TokenStore(tmp_path / "tokens.json")
    service = _service(access_token, store, FakeClock(1000))

    token = service.exchange_authorization_code("authorization-code")

    assert token.access_token == "u-access"
    assert token.refresh_token == "ur-refresh"
    assert store.load() == token
    assert access_token.exchange_calls == [
        {
            "code": "authorization-code",
            "redirect_uri": "http://127.0.0.1:8765/callback",
            "scope": "docx:document wiki:wiki offline_access",
        }
    ]


def test_expiring_access_token_is_refreshed_and_new_refresh_token_is_saved(
    tmp_path: Path,
) -> None:
    clock = FakeClock(1000)
    store = TokenStore(tmp_path / "tokens.json")
    store.save(
        StoredUserToken(
            access_token="u-old",
            refresh_token="ur-old",
            access_token_expires_at=1100,
            refresh_token_expires_at=2000,
            scope="old-scope",
        )
    )
    access_token = FakeAccessToken(
        refresh=SimpleNamespace(
            access_token="u-new",
            refresh_token="ur-new",
            expires_in=7200,
            refresh_token_expires_in=2_592_000,
            scope="new-scope",
        )
    )
    service = _service(access_token, store, clock)

    option = asyncio.run(service.get_request_option())
    saved = store.load()

    assert option.user_access_token == "u-new"
    assert saved is not None
    assert saved.refresh_token == "ur-new"
    assert saved.access_token_expires_at == 8200
    assert access_token.refresh_calls == [
        {
            "refresh_token": "ur-old",
            "scope": "docx:document wiki:wiki offline_access",
        }
    ]


def test_valid_token_is_used_without_refresh(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    store.save(
        StoredUserToken(
            access_token="u-valid",
            refresh_token="ur-valid",
            access_token_expires_at=2000,
            refresh_token_expires_at=3000,
        )
    )
    access_token = FakeAccessToken()
    service = _service(access_token, store, FakeClock(1000))

    option = asyncio.run(service.get_request_option())

    assert option.user_access_token == "u-valid"
    assert access_token.refresh_calls == []


def test_expired_refresh_token_requires_login(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    store.save(
        StoredUserToken(
            access_token="u-expired",
            refresh_token="ur-expired",
            access_token_expires_at=900,
            refresh_token_expires_at=999,
        )
    )
    service = _service(FakeAccessToken(), store, FakeClock(1000))

    with pytest.raises(FeishuAuthError, match="feishu-mcp login"):
        asyncio.run(service.get_request_option())


def test_missing_token_requires_login(tmp_path: Path) -> None:
    service = _service(
        FakeAccessToken(),
        TokenStore(tmp_path / "missing.json"),
        FakeClock(1000),
    )

    with pytest.raises(FeishuAuthError, match="feishu-mcp login"):
        asyncio.run(service.get_request_option())
