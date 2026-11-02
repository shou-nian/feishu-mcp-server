"""基于环境变量的应用配置。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    feishu_auth_mode: Literal["tenant", "user"] = Field(
        default="tenant",
        validation_alias="FEISHU_AUTH_MODE",
    )
    feishu_redirect_uri: str = Field(
        default="http://127.0.0.1:8765/callback",
        min_length=1,
        validation_alias="FEISHU_REDIRECT_URI",
    )
    feishu_user_scopes: str = Field(
        default="docx:document:readonly wiki:wiki:readonly offline_access",
        min_length=1,
        validation_alias="FEISHU_USER_SCOPES",
    )
    feishu_token_file: Path = Field(
        default_factory=lambda: Path.home() / ".feishu-mcp" / "tokens.json",
        validation_alias="FEISHU_TOKEN_FILE",
    )
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

    @property
    def user_scope_list(self) -> list[str]:
        """返回去重且保持顺序的用户授权 scope。"""

        return list(dict.fromkeys(self.feishu_user_scopes.split()))

    @field_validator("feishu_token_file")
    @classmethod
    def expand_token_file(cls, path: Path) -> Path:
        """展开 token 文件路径中的用户目录。"""

        return path.expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存配置，避免重复解析环境变量。"""

    return Settings()  # type: ignore[call-arg]
