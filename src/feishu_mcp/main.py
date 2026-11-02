"""飞书 MCP Server 的 stdio 运行生命周期。"""

import asyncio
import logging
import signal
from types import FrameType
from typing import Any

from mcp.server.fastmcp import FastMCP
from feishu_mcp.tools import mcp

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
    """委托 CLI 解析 serve/login 命令。"""

    from feishu_mcp.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
