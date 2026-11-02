"""环境变量配置测试。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from feishu_mcp.config.settings import Settings


def test_app_credentials_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    error = str(exc_info.value)
    assert "FEISHU_APP_ID" in error
    assert "FEISHU_APP_SECRET" in error


def test_app_credentials_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.feishu_app_id == "cli_test"
    assert settings.feishu_app_secret.get_secret_value() == "secret"
    assert settings.feishu_auth_mode == "tenant"
    assert settings.user_scope_list == [
        "docx:document",
        "wiki:wiki:readonly",
        "bitable:app",
        "offline_access",
    ]


def test_user_auth_settings_are_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_AUTH_MODE", "user")
    monkeypatch.setenv("FEISHU_REDIRECT_URI", "http://127.0.0.1:9876/callback")
    monkeypatch.setenv(
        "FEISHU_USER_SCOPES",
        "docx:document wiki:wiki:readonly bitable:app offline_access",
    )
    monkeypatch.setenv("FEISHU_TOKEN_FILE", "~/custom-tokens.json")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.feishu_auth_mode == "user"
    assert settings.feishu_redirect_uri == "http://127.0.0.1:9876/callback"
    assert settings.feishu_token_file == Path("~/custom-tokens.json").expanduser()
    assert settings.user_scope_list == [
        "docx:document",
        "wiki:wiki:readonly",
        "bitable:app",
        "offline_access",
    ]


def test_invalid_auth_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_AUTH_MODE", "oauth")

    with pytest.raises(ValidationError, match="FEISHU_AUTH_MODE"):
        Settings(_env_file=None)  # type: ignore[call-arg]
