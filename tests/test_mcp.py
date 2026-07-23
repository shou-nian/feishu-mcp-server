"""MCP Tool 注册、校验、错误转换和优雅退出测试。"""

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from feishu_mcp.feishu.errors import FeishuAPIError
from feishu_mcp.main import run_server
from feishu_mcp.models.schemas import (
    AppendDocumentResult,
    CreateDocumentResult,
    DocumentResult,
    UpdateDocumentResult,
)
from feishu_mcp.tools import create_mcp_server


class FakeDocumentService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.error: Exception | None = None

    async def read_document(self, document_id: str) -> DocumentResult:
        self.calls.append(("read", (document_id,)))
        if self.error:
            raise self.error
        return DocumentResult(
            document_id=document_id,
            title="标题",
            content="正文",
            blocks=[],
        )

    async def create_document(self, title: str, content: str) -> CreateDocumentResult:
        self.calls.append(("create", (title, content)))
        if self.error:
            raise self.error
        return CreateDocumentResult(document_id="new-doc", url="https://feishu.cn/docx/new-doc")

    async def update_document(self, document_id: str, content: str) -> UpdateDocumentResult:
        self.calls.append(("update", (document_id, content)))
        if self.error:
            raise self.error
        return UpdateDocumentResult(document_id=document_id, block_count=1)

    async def append_document(self, document_id: str, content: str) -> AppendDocumentResult:
        self.calls.append(("append", (document_id, content)))
        if self.error:
            raise self.error
        return AppendDocumentResult(document_id=document_id, appended=True, block_count=1)


def test_four_tools_are_registered() -> None:
    server = create_mcp_server(document_service=FakeDocumentService())  # type: ignore[arg-type]

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "read_feishu_document",
        "create_feishu_document",
        "update_feishu_document",
        "append_feishu_document",
    }
    read_tool = next(tool for tool in tools if tool.name == "read_feishu_document")
    assert read_tool.inputSchema["properties"]["document_id"]["minLength"] == 1


def test_tool_call_returns_structured_result() -> None:
    service = FakeDocumentService()
    server = create_mcp_server(document_service=service)  # type: ignore[arg-type]

    _, structured_result = asyncio.run(
        server.call_tool("read_feishu_document", {"document_id": "doc1"})
    )

    assert structured_result == {
        "document_id": "doc1",
        "title": "标题",
        "content": "正文",
        "blocks": [],
    }
    assert service.calls == [("read", ("doc1",))]


def test_tool_argument_validation_rejects_empty_document_id() -> None:
    server = create_mcp_server(document_service=FakeDocumentService())  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="validation error"):
        asyncio.run(server.call_tool("read_feishu_document", {"document_id": ""}))


def test_append_tool_returns_structured_result() -> None:
    service = FakeDocumentService()
    server = create_mcp_server(document_service=service)  # type: ignore[arg-type]

    _, structured_result = asyncio.run(
        server.call_tool(
            "append_feishu_document",
            {"document_id": "doc1", "content": "追加内容"},
        )
    )

    assert structured_result == {
        "document_id": "doc1",
        "appended": True,
        "block_count": 1,
    }
    assert service.calls == [("append", ("doc1", "追加内容"))]


def test_append_tool_rejects_empty_content() -> None:
    server = create_mcp_server(document_service=FakeDocumentService())  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="validation error"):
        asyncio.run(
            server.call_tool(
                "append_feishu_document",
                {"document_id": "doc1", "content": ""},
            )
        )


def test_feishu_error_is_converted_to_tool_error() -> None:
    service = FakeDocumentService()
    service.error = FeishuAPIError("飞书文档不存在")
    server = create_mcp_server(document_service=service)  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="飞书文档不存在"):
        asyncio.run(server.call_tool("read_feishu_document", {"document_id": "missing"}))


def test_run_server_cancels_task_on_shutdown_event() -> None:
    class BlockingServer:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cleaned_up = False

        async def run_stdio_async(self) -> None:
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned_up = True

    async def scenario() -> bool:
        server = BlockingServer()
        shutdown = asyncio.Event()
        task = asyncio.create_task(
            run_server(  # type: ignore[arg-type]
                server,
                shutdown_event=shutdown,
                install_signal_handlers=False,
            )
        )
        await server.started.wait()
        shutdown.set()
        await asyncio.wait_for(task, timeout=1)
        return server.cleaned_up

    assert asyncio.run(scenario()) is True
