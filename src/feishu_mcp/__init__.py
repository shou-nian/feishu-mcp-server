"""飞书 MCP Server 的公开入口。"""


def main() -> None:
    """启动飞书 MCP stdio Server。"""

    from feishu_mcp.main import main as run_server

    run_server()


__all__ = ["main"]
