"""环境变量配置测试。"""

import pytest
from pydantic import ValidationError

from src.config.settings import Settings


def test_feishu_base_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEISHU_BASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(  # type: ignore[call-arg]
            FEISHU_APP_ID="cli_test",
            FEISHU_APP_SECRET="secret",
            _env_file=None,
        )

    assert "FEISHU_BASE_URL" in str(exc_info.value)


def test_feishu_base_url_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_BASE_URL", "https://open.example.feishu.cn")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.feishu_base_url == "https://open.example.feishu.cn"
