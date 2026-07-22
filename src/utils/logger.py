"""不会污染 MCP stdio 通道的日志配置。"""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """将应用日志统一输出到 stderr。"""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
