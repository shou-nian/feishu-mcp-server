"""飞书 MCP Server 的 stdio 入口。"""

import asyncio
import logging
import signal
from types import FrameType
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from src.config.settings import get_settings
from src.mcp.tools import mcp
from src.utils.logger import configure_logging

LOGGER = logging.getLogger(__name__)
SHUTDOWN_SIGNALS = tuple(
    sig for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)) if sig
)


async def run_server(
    server: FastMCP[Any] = mcp,
    *,
    shutdown_event: asyncio.Event | None = None,
    install_signal_handlers: bool = True,
) -> None:
    """运行 stdio Server，并在 EOF 或退出信号后清理生命周期资源。"""

    stop_event = shutdown_event or asyncio.Event()
    restore_handlers: list[tuple[signal.Signals, Any]] = []
    loop_handlers: list[signal.Signals] = []
    loop = asyncio.get_running_loop()

    def request_shutdown(signum: int | None = None, _: FrameType | None = None) -> None:
        if signum is not None:
            LOGGER.info("收到退出信号 %s，正在优雅关闭", signum)
        loop.call_soon_threadsafe(stop_event.set)

    if install_signal_handlers:
        for sig in SHUTDOWN_SIGNALS:
            try:
                loop.add_signal_handler(sig, request_shutdown, int(sig))
                loop_handlers.append(sig)
            except (NotImplementedError, RuntimeError):
                previous = signal.getsignal(sig)
                signal.signal(sig, request_shutdown)
                restore_handlers.append((sig, previous))

    server_task = asyncio.create_task(server.run_stdio_async(), name="mcp-stdio-server")
    stop_task = asyncio.create_task(stop_event.wait(), name="mcp-shutdown-waiter")
    try:
        done, _ = await asyncio.wait(
            {server_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if server_task in done:
            await server_task
        else:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
    finally:
        stop_task.cancel()
        try:
            await stop_task
        except asyncio.CancelledError:
            pass
        for sig in loop_handlers:
            loop.remove_signal_handler(sig)
        for sig, previous in restore_handlers:
            signal.signal(sig, previous)


def main() -> None:
    """命令行入口；仅向 stderr 写日志，避免破坏 MCP stdio 协议。"""

    try:
        settings = get_settings()
        configure_logging(settings.log_level)
        asyncio.run(run_server())
    except KeyboardInterrupt:
        LOGGER.info("飞书 MCP Server 已停止")
    except ValidationError:
        configure_logging()
        LOGGER.error(
            "配置错误：请设置有效的 FEISHU_APP_ID、FEISHU_APP_SECRET 和 FEISHU_BASE_URL"
        )
        raise SystemExit(2) from None
    except Exception as exc:
        LOGGER.error("飞书 MCP Server 启动或运行失败：%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
