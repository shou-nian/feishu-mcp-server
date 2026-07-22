"""基于环境变量的应用配置。"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """飞书 MCP Server 运行配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    feishu_app_id: str = Field(min_length=1, validation_alias="FEISHU_APP_ID")
    feishu_app_secret: SecretStr = Field(min_length=1, validation_alias="FEISHU_APP_SECRET")
    feishu_base_url: str = Field(min_length=1, validation_alias="FEISHU_BASE_URL")
    feishu_document_url_base: str = Field(
        default="https://feishu.cn/docx",
        validation_alias="FEISHU_DOCUMENT_URL_BASE",
    )
    feishu_request_timeout: float = Field(
        default=15.0,
        gt=0,
        validation_alias="FEISHU_REQUEST_TIMEOUT",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存配置，避免重复解析环境变量。"""

    return Settings()  # type: ignore[call-arg]
