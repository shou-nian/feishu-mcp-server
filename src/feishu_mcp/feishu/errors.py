"""飞书集成层的异常定义。"""


class FeishuError(Exception):
    """可安全返回给 MCP Client 的飞书业务异常。"""


class FeishuAuthError(FeishuError):
    """飞书应用鉴权失败。"""


class FeishuAPIError(FeishuError):
    """飞书开放平台 API 调用失败。"""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class FeishuConfigurationError(FeishuError):
    """服务端配置不完整或不合法。"""
