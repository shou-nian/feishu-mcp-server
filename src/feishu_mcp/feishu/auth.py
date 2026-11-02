"""飞书官方 SDK 客户端构建与鉴权配置。"""

import lark_oapi as lark

from feishu_mcp.config.settings import Settings

FEISHU_BASE_URL = "https://open.feishu.cn"
FEISHU_ACCOUNTS_URL = "https://accounts.feishu.cn"


def build_lark_client(settings: Settings) -> lark.Client:
    """按鉴权模式构建飞书官方 SDK 客户端。"""

    log_level_name = settings.log_level.upper()
    if log_level_name == "WARN":
        log_level_name = "WARNING"
    sdk_log_level = getattr(
        lark.LogLevel,
        log_level_name,
        lark.LogLevel.WARNING,
    )
    builder = (
        lark.Client.builder()
        .app_id(settings.feishu_app_id)
        .app_secret(settings.feishu_app_secret.get_secret_value())
        .domain(FEISHU_BASE_URL)
        .oauth_base_url(FEISHU_ACCOUNTS_URL)
        .timeout(settings.feishu_request_timeout)
        .log_level(sdk_log_level)
    )
    if settings.feishu_auth_mode == "user":
        builder.enable_set_token(True)
    return builder.build()
