"""飞书文档 MCP Tools 定义。"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from feishu_mcp.config.settings import Settings, get_settings
from feishu_mcp.feishu.bitable import FeishuBitableService
from feishu_mcp.feishu.client import FeishuClient
from feishu_mcp.feishu.document import FeishuDocumentService
from feishu_mcp.feishu.errors import FeishuError

LOGGER = logging.getLogger(__name__)

DocumentId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="飞书 Docx 文档 ID"),
]
DocumentTitle = Annotated[
    str,
    Field(min_length=1, max_length=800, description="新文档标题"),
]
MarkdownContent = Annotated[
    str,
    Field(max_length=1_000_000, description="Markdown 格式的文档正文"),
]
AppendContent = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1_000_000,
        description="需要追加的 Markdown 或普通文本正文",
    ),
]
BitableToken = Annotated[
    str,
    Field(min_length=1, max_length=256, description="Bitable app_token（多维表格 Token）"),
]
BitableTableId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="Bitable table_id（数据表 ID）"),
]
BitableRecordFields = Annotated[
    dict[str, Any],
    Field(min_length=1, description="以字段名称或 field_id 为 key 的记录字段值"),
]


@dataclass(slots=True)
class ToolRuntime:
    """Tool 生命周期内共享的 Docx 与 Bitable 服务。"""

    service: FeishuDocumentService | None = None
    bitable_service: FeishuBitableService | None = None

    def require_service(self) -> FeishuDocumentService:
        if self.service is None:
            raise ToolError("飞书文档服务尚未初始化")
        return self.service

    def require_bitable_service(self) -> FeishuBitableService:
        if self.bitable_service is None:
            raise ToolError("飞书 Bitable 服务尚未初始化")
        return self.bitable_service


def create_mcp_server(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    document_service: FeishuDocumentService | None = None,
    bitable_service: FeishuBitableService | None = None,
) -> FastMCP[Any]:
    """创建并注册飞书 Tools；测试可注入内存 service。"""

    runtime = ToolRuntime(service=document_service, bitable_service=bitable_service)

    @asynccontextmanager
    async def lifespan(_: FastMCP[Any]):
        owns_service = runtime.service is None
        owns_bitable_service = runtime.bitable_service is None
        if owns_service or owns_bitable_service:
            settings = settings_factory()
            client = FeishuClient.from_settings(settings)
            if owns_service:
                runtime.service = FeishuDocumentService(
                    client,
                    document_url_base=settings.feishu_document_url_base,
                )
            if owns_bitable_service:
                runtime.bitable_service = FeishuBitableService(client)
        try:
            yield {}
        finally:
            if owns_service:
                runtime.service = None
            if owns_bitable_service:
                runtime.bitable_service = None

    server = FastMCP(
        name="feishu-document",
        instructions=(
            "读取、创建、全量更新和追加飞书 Docx 文档；查询 Bitable 字段并按结构新增记录。"
        ),
        lifespan=lifespan,
        log_level="WARNING",
    )

    @server.tool(
        name="read_feishu_document",
        description="读取飞书文档标题、Markdown 正文（含表格）和原始 block 结构。",
    )
    async def read_feishu_document(document_id: DocumentId) -> dict[str, Any]:
        try:
            result = await runtime.require_service().read_document(document_id)
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("读取飞书文档时发生内部错误")
            raise ToolError("读取飞书文档失败，服务内部发生错误") from None

    @server.tool(
        name="create_feishu_document",
        description="创建飞书文档，并把 Markdown 正文（含表格）转换为飞书 blocks。",
    )
    async def create_feishu_document(
        title: DocumentTitle,
        content: MarkdownContent,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_service().create_document(title, content)
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("创建飞书文档时发生内部错误")
            raise ToolError("创建飞书文档失败，服务内部发生错误") from None

    @server.tool(
        name="update_feishu_document",
        description="用 Markdown（含表格）全量替换指定飞书文档的正文。",
    )
    async def update_feishu_document(
        document_id: DocumentId,
        content: MarkdownContent,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_service().update_document(document_id, content)
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("更新飞书文档时发生内部错误")
            raise ToolError("更新飞书文档失败，服务内部发生错误") from None

    @server.tool(
        name="append_feishu_document",
        description=(
            "在飞书文档末尾追加 Markdown、普通文本或表格；不会删除、覆盖或清空已有内容。"
        ),
    )
    async def append_feishu_document(
        document_id: DocumentId,
        content: AppendContent,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_service().append_document(document_id, content)
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("追加飞书文档时发生内部错误")
            raise ToolError("追加飞书文档失败，服务内部发生错误") from None

    @server.tool(
        name="list_feishu_bitable_fields",
        description="分页查询飞书多维表格字段结构、类型、选项和是否可写。",
    )
    async def list_feishu_bitable_fields(
        app_token: BitableToken,
        table_id: BitableTableId,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_service().list_fields(app_token, table_id)
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("查询 Bitable 字段时发生内部错误")
            raise ToolError("查询 Bitable 字段失败，服务内部发生错误") from None

    @server.tool(
        name="create_feishu_bitable_record",
        description=(
            "先查询 Bitable 字段结构并校验字段名称、类型、选项和只读属性，再新增一条记录。"
        ),
    )
    async def create_feishu_bitable_record(
        app_token: BitableToken,
        table_id: BitableTableId,
        fields: BitableRecordFields,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_service().create_record(
                app_token,
                table_id,
                fields,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("新增 Bitable 记录时发生内部错误")
            raise ToolError("新增 Bitable 记录失败，服务内部发生错误") from None

    return server


mcp = create_mcp_server()
