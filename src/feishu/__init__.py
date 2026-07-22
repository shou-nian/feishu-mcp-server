"""飞书开放平台集成。"""

from src.feishu.client import FeishuClient
from src.feishu.document import FeishuDocumentService
from src.feishu.errors import FeishuAPIError, FeishuAuthError, FeishuError

__all__ = [
    "FeishuAPIError",
    "FeishuAuthError",
    "FeishuClient",
    "FeishuDocumentService",
    "FeishuError",
]
