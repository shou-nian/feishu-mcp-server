"""MCP Tool 注册、校验、错误转换和优雅退出测试。"""

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from feishu_mcp.feishu.errors import FeishuAPIError
from feishu_mcp.main import run_server
from feishu_mcp.models.schemas import (
    AppendDocumentResult,
    BitableFieldSchema,
    BitableFieldsResult,
    BitableRecordResult,
    BitableRecordSchema,
    BitableRecordsResult,
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


class FakeBitableService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def list_fields(self, app_token: str, table_id: str) -> BitableFieldsResult:
        self.calls.append(("list_fields", (app_token, table_id)))
        return BitableFieldsResult(
            app_token=app_token,
            table_id=table_id,
            fields=[
                BitableFieldSchema(
                    field_id="fld1",
                    field_name="标题",
                    type=1,
                    type_name="text",
                    writable=True,
                )
            ],
        )

    async def create_record(
        self,
        app_token: str,
        table_id: str,
        values: dict[str, Any],
    ) -> BitableRecordResult:
        self.calls.append(("create_record", (app_token, table_id, values)))
        return BitableRecordResult(
            app_token=app_token,
            table_id=table_id,
            record_id="rec1",
            fields=values,
        )

    async def list_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
        filter_expression: str | None = None,
    ) -> BitableRecordsResult:
        self.calls.append(
            (
                "list_records",
                (app_token, table_id, page_size, page_token, filter_expression),
            )
        )
        return BitableRecordsResult(
            app_token=app_token,
            table_id=table_id,
            records=[BitableRecordSchema(record_id="rec1", fields={"状态": "是"})],
            has_more=False,
            total=1,
        )

    async def update_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        values: dict[str, Any],
    ) -> BitableRecordResult:
        self.calls.append(("update_record", (app_token, table_id, record_id, values)))
        return BitableRecordResult(
            app_token=app_token,
            table_id=table_id,
            record_id=record_id,
            fields=values,
        )


def test_eight_tools_are_registered() -> None:
    server = create_mcp_server(document_service=FakeDocumentService())  # type: ignore[arg-type]

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "read_feishu_document",
        "create_feishu_document",
        "update_feishu_document",
        "append_feishu_document",
        "list_feishu_bitable_fields",
        "create_feishu_bitable_record",
        "list_feishu_bitable_records",
        "update_feishu_bitable_record",
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


def test_bitable_tools_return_structured_results() -> None:
    bitable_service = FakeBitableService()
    server = create_mcp_server(
        document_service=FakeDocumentService(),  # type: ignore[arg-type]
        bitable_service=bitable_service,  # type: ignore[arg-type]
    )

    _, fields_result = asyncio.run(
        server.call_tool(
            "list_feishu_bitable_fields",
            {"app_token": "app1", "table_id": "tbl1"},
        )
    )
    _, record_result = asyncio.run(
        server.call_tool(
            "create_feishu_bitable_record",
            {
                "app_token": "app1",
                "table_id": "tbl1",
                "fields": {"标题": "内容"},
            },
        )
    )
    _, records_result = asyncio.run(
        server.call_tool(
            "list_feishu_bitable_records",
            {
                "app_token": "app1",
                "table_id": "tbl1",
                "filter_expression": 'CurrentValue.[状态]="是"',
                "page_size": 50,
            },
        )
    )
    _, update_result = asyncio.run(
        server.call_tool(
            "update_feishu_bitable_record",
            {
                "app_token": "app1",
                "table_id": "tbl1",
                "record_id": "rec1",
                "fields": {"状态": "是", "标签": ["重要"]},
            },
        )
    )

    assert fields_result["fields"][0]["field_name"] == "标题"  # type: ignore[index]
    assert record_result == {  # type: ignore[comparison-overlap]
        "app_token": "app1",
        "table_id": "tbl1",
        "record_id": "rec1",
        "fields": {"标题": "内容"},
    }
    assert records_result["records"][0]["record_id"] == "rec1"  # type: ignore[index]
    assert update_result == {  # type: ignore[comparison-overlap]
        "app_token": "app1",
        "table_id": "tbl1",
        "record_id": "rec1",
        "fields": {"状态": "是", "标签": ["重要"]},
    }
    assert bitable_service.calls == [
        ("list_fields", ("app1", "tbl1")),
        ("create_record", ("app1", "tbl1", {"标题": "内容"})),
        (
            "list_records",
            ("app1", "tbl1", 50, None, 'CurrentValue.[状态]="是"'),
        ),
        (
            "update_record",
            ("app1", "tbl1", "rec1", {"状态": "是", "标签": ["重要"]}),
        ),
    ]


def test_bitable_record_tool_argument_validation() -> None:
    server = create_mcp_server(
        document_service=FakeDocumentService(),  # type: ignore[arg-type]
        bitable_service=FakeBitableService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ToolError, match="validation error"):
        asyncio.run(
            server.call_tool(
                "list_feishu_bitable_records",
                {"app_token": "app1", "table_id": "tbl1", "page_size": 0},
            )
        )

    with pytest.raises(ToolError, match="validation error"):
        asyncio.run(
            server.call_tool(
                "update_feishu_bitable_record",
                {
                    "app_token": "app1",
                    "table_id": "tbl1",
                    "record_id": "",
                    "fields": {"状态": "是"},
                },
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
