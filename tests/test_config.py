"""环境变量配置测试。"""

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
