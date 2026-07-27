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
from feishu_mcp.feishu.bitable_structure import FeishuBitableStructureService
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
BitableRecordId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="需要更新的 Bitable record_id"),
]
BitableFilterExpression = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2_000,
        description="可选的飞书 Bitable filter 表达式，用于定位记录",
    ),
]
BitablePageSize = Annotated[
    int,
    Field(ge=1, le=500, description="每页记录数，范围 1—500"),
]
BitablePageToken = Annotated[
    str,
    Field(min_length=1, max_length=1_000, description="上一页返回的分页 token"),
]
BitableRecordFields = Annotated[
    dict[str, Any],
    Field(min_length=1, description="以字段名称或 field_id 为 key 的记录字段值"),
]
BitableFieldName = Annotated[
    str,
    Field(min_length=1, max_length=100, description="需要创建的 Bitable 字段名称"),
]
BitableFormulaExpression = Annotated[
    str,
    Field(min_length=1, max_length=20_000, description="飞书 Bitable 公式表达式"),
]
BitableViewName = Annotated[
    str,
    Field(min_length=1, max_length=100, description="需要创建的 Bitable 视图名称"),
]
BitableViewType = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        description="视图类型：grid、kanban、gallery、gantt 或 form",
    ),
]
BitableDashboardBlockId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="作为复制模板的仪表盘 block_id"),
]
BitableDashboardName = Annotated[
    str,
    Field(min_length=1, max_length=100, description="复制后新仪表盘的名称"),
]
BitableDashboardPageSize = Annotated[
    int,
    Field(ge=1, le=100, description="每页仪表盘数，范围 1—100"),
]


@dataclass(slots=True)
class ToolRuntime:
    """Tool 生命周期内共享的 Docx 与 Bitable 服务。"""

    service: FeishuDocumentService | None = None
    bitable_service: FeishuBitableService | None = None
    bitable_structure_service: FeishuBitableStructureService | None = None

    def require_service(self) -> FeishuDocumentService:
        if self.service is None:
            raise ToolError("飞书文档服务尚未初始化")
        return self.service

    def require_bitable_service(self) -> FeishuBitableService:
        if self.bitable_service is None:
            raise ToolError("飞书 Bitable 服务尚未初始化")
        return self.bitable_service

    def require_bitable_structure_service(self) -> FeishuBitableStructureService:
        if self.bitable_structure_service is None:
            raise ToolError("飞书 Bitable 结构服务尚未初始化")
        return self.bitable_structure_service


def create_mcp_server(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    document_service: FeishuDocumentService | None = None,
    bitable_service: FeishuBitableService | None = None,
    bitable_structure_service: FeishuBitableStructureService | None = None,
) -> FastMCP[Any]:
    """创建并注册飞书 Tools；测试可注入内存 service。"""

    runtime = ToolRuntime(
        service=document_service,
        bitable_service=bitable_service,
        bitable_structure_service=bitable_structure_service,
    )

    @asynccontextmanager
    async def lifespan(_: FastMCP[Any]):
        owns_service = runtime.service is None
        owns_bitable_service = runtime.bitable_service is None
        owns_bitable_structure_service = runtime.bitable_structure_service is None
        if owns_service or owns_bitable_service or owns_bitable_structure_service:
            settings = settings_factory()
            client = FeishuClient.from_settings(settings)
            if owns_service:
                runtime.service = FeishuDocumentService(
                    client,
                    document_url_base=settings.feishu_document_url_base,
                )
            if owns_bitable_service:
                runtime.bitable_service = FeishuBitableService(client)
            if owns_bitable_structure_service:
                runtime.bitable_structure_service = FeishuBitableStructureService(client)
        try:
            yield {}
        finally:
            if owns_service:
                runtime.service = None
            if owns_bitable_service:
                runtime.bitable_service = None
            if owns_bitable_structure_service:
                runtime.bitable_structure_service = None

    server = FastMCP(
        name="feishu-document",
        instructions=(
            "读取、创建、全量更新和追加飞书 Docx 文档；"
            "查询 Bitable 字段与记录，按字段结构写入记录，并创建公式字段、视图或复制仪表盘。"
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
        name="list_feishu_bitable_records",
        description=(
            "分页查询飞书多维表格记录，可传入 Bitable filter 表达式定位目标行；"
            "返回用于精确更新的 record_id。"
        ),
    )
    async def list_feishu_bitable_records(
        app_token: BitableToken,
        table_id: BitableTableId,
        filter_expression: BitableFilterExpression | None = None,
        page_size: BitablePageSize = 100,
        page_token: BitablePageToken | None = None,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_service().list_records(
                app_token,
                table_id,
                page_size=page_size,
                page_token=page_token,
                filter_expression=filter_expression,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("查询 Bitable 记录时发生内部错误")
            raise ToolError("查询 Bitable 记录失败，服务内部发生错误") from None

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

    @server.tool(
        name="update_feishu_bitable_record",
        description=(
            "通过 record_id 更新指定 Bitable 行。更新前读取实时字段结构；"
            "单选传选项名称字符串，多选传选项名称数组。"
        ),
    )
    async def update_feishu_bitable_record(
        app_token: BitableToken,
        table_id: BitableTableId,
        record_id: BitableRecordId,
        fields: BitableRecordFields,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_service().update_record(
                app_token,
                table_id,
                record_id,
                fields,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("更新 Bitable 记录时发生内部错误")
            raise ToolError("更新 Bitable 记录失败，服务内部发生错误") from None

    @server.tool(
        name="create_feishu_bitable_formula_field",
        description="在指定 Bitable 数据表中创建公式字段，公式表达式按飞书语法原样提交。",
    )
    async def create_feishu_bitable_formula_field(
        app_token: BitableToken,
        table_id: BitableTableId,
        field_name: BitableFieldName,
        formula_expression: BitableFormulaExpression,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_structure_service().create_formula_field(
                app_token,
                table_id,
                field_name,
                formula_expression,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("创建 Bitable 公式字段时发生内部错误")
            raise ToolError("创建 Bitable 公式字段失败，服务内部发生错误") from None

    @server.tool(
        name="create_feishu_bitable_view",
        description="在指定数据表中创建 grid、kanban、gallery、gantt 或 form 视图。",
    )
    async def create_feishu_bitable_view(
        app_token: BitableToken,
        table_id: BitableTableId,
        view_name: BitableViewName,
        view_type: BitableViewType = "grid",
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_structure_service().create_view(
                app_token,
                table_id,
                view_name,
                view_type,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("创建 Bitable 视图时发生内部错误")
            raise ToolError("创建 Bitable 视图失败，服务内部发生错误") from None

    @server.tool(
        name="list_feishu_bitable_dashboards",
        description="分页查询 Bitable 仪表盘，返回可用于复制模板的 block_id。",
    )
    async def list_feishu_bitable_dashboards(
        app_token: BitableToken,
        page_size: BitableDashboardPageSize = 100,
        page_token: BitablePageToken | None = None,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_structure_service().list_dashboards(
                app_token,
                page_size=page_size,
                page_token=page_token,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("查询 Bitable 仪表盘时发生内部错误")
            raise ToolError("查询 Bitable 仪表盘失败，服务内部发生错误") from None

    @server.tool(
        name="copy_feishu_bitable_dashboard",
        description=(
            "通过官方复制接口从已有仪表盘模板创建新仪表盘，并复制模板中的全部组件。"
        ),
    )
    async def copy_feishu_bitable_dashboard(
        app_token: BitableToken,
        source_block_id: BitableDashboardBlockId,
        name: BitableDashboardName,
    ) -> dict[str, Any]:
        try:
            result = await runtime.require_bitable_structure_service().copy_dashboard(
                app_token,
                source_block_id,
                name,
            )
            return result.model_dump()
        except FeishuError as exc:
            raise ToolError(str(exc)) from None
        except ToolError:
            raise
        except Exception:
            LOGGER.exception("复制 Bitable 仪表盘时发生内部错误")
            raise ToolError("复制 Bitable 仪表盘失败，服务内部发生错误") from None

    return server


mcp = create_mcp_server()
