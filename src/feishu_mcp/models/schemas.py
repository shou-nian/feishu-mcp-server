"""MCP Tool 的结构化响应模型。"""

from typing import Any

from pydantic import BaseModel, Field


class DocumentResult(BaseModel):
    """读取飞书文档的结果。"""

    document_id: str
    title: str
    content: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class CreateDocumentResult(BaseModel):
    """创建飞书文档的结果。"""

    document_id: str
    url: str


class UpdateDocumentResult(BaseModel):
    """更新飞书文档的结果。"""

    document_id: str
    updated: bool = True
    block_count: int = Field(ge=0)


class AppendDocumentResult(BaseModel):
    """追加飞书文档正文的结果。"""

    document_id: str
    appended: bool
    block_count: int = Field(ge=0)
