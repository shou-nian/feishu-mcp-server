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


class BitableFieldSchema(BaseModel):
    """Bitable 字段结构。"""

    field_id: str
    field_name: str
    type: int
    type_name: str
    ui_type: str | None = None
    is_primary: bool = False
    is_hidden: bool = False
    writable: bool
    options: list[str] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)


class BitableFieldsResult(BaseModel):
    """Bitable 字段查询结果。"""

    app_token: str
    table_id: str
    fields: list[BitableFieldSchema]


class BitableRecordResult(BaseModel):
    """Bitable 新增或更新记录结果。"""

    app_token: str
    table_id: str
    record_id: str
    fields: dict[str, Any]


class BitableRecordSchema(BaseModel):
    """Bitable 单条记录。"""

    record_id: str
    fields: dict[str, Any]
    created_time: int | None = None
    last_modified_time: int | None = None
    record_url: str | None = None


class BitableRecordsResult(BaseModel):
    """Bitable 分页记录查询结果。"""

    app_token: str
    table_id: str
    records: list[BitableRecordSchema]
    has_more: bool
    page_token: str | None = None
    total: int | None = None
