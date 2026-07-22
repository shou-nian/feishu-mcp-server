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


@dataclass(slots=True)
class ToolRuntime:
    """Tool 生命周期内共享的文档服务。"""

    service: FeishuDocumentService | None = None

    def require_service(self) -> FeishuDocumentService:
        if self.service is None:
            raise ToolError("飞书文档服务尚未初始化")
        return self.service


def create_mcp_server(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    document_service: FeishuDocumentService | None = None,
) -> FastMCP[Any]:
    """创建并注册飞书文档 Tools；测试可注入内存 service。"""

    runtime = ToolRuntime(service=document_service)

    @asynccontextmanager
    async def lifespan(_: FastMCP[Any]):
        client: FeishuClient | None = None
        if runtime.service is None:
            settings = settings_factory()
            client = FeishuClient.from_settings(settings)
            runtime.service = FeishuDocumentService(
                client,
                document_url_base=settings.feishu_document_url_base,
            )
        try:
            yield {}
        finally:
            if client is not None:
                await client.aclose()
                runtime.service = None

    server = FastMCP(
        name="feishu-document",
        instructions="读取、创建和全量更新飞书 Docx 文档。正文使用 Markdown。",
        lifespan=lifespan,
        log_level="WARNING",
    )

    @server.tool(
        name="read_feishu_document",
        description="读取飞书文档标题、Markdown 正文和原始 block 结构。",
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
        description="创建飞书文档，并把 Markdown 正文转换为飞书 blocks。",
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
        description="用 Markdown 全量替换指定飞书文档的正文。",
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

    return server


mcp = create_mcp_server()
