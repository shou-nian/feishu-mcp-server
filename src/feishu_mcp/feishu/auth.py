"""飞书官方 SDK 客户端构建与鉴权配置。"""

import lark_oapi as lark

from feishu_mcp.config.settings import Settings

FEISHU_BASE_URL = "https://open.feishu.cn"


def build_lark_client(settings: Settings) -> lark.Client:
    """构建由官方 SDK 管理 tenant_access_token 的异步客户端。"""

    log_level_name = settings.log_level.upper()
    if log_level_name == "WARN":
        log_level_name = "WARNING"
    sdk_log_level = getattr(
        lark.LogLevel,
        log_level_name,
        lark.LogLevel.WARNING,
    )
    return (
        lark.Client.builder()
        .app_id(settings.feishu_app_id)
        .app_secret(settings.feishu_app_secret.get_secret_value())
        .domain(FEISHU_BASE_URL)
        .timeout(settings.feishu_request_timeout)
        .log_level(sdk_log_level)
        .build()
    )
