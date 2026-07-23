"""文档、Markdown 与表格测试，全部使用内存 fake SDK Client。"""

import asyncio
from typing import Any

from lark_oapi.api.docx.v1 import Block, Document, Table, TableProperty

from feishu_mcp.feishu.document import (
    TABLE_BLOCK_TYPE,
    FeishuDocumentService,
    blocks_to_markdown,
    markdown_to_blocks,
)


class FakeFeishuClient:
    def __init__(self) -> None:
        self.document = Document.builder().document_id("doc1").title("示例文档").build()
        self.block_pages: list[tuple[list[Block], bool, str | None]] = []
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def get_document(self, document_id: str) -> Document:
        self.calls.append(("get_document", (document_id,), {}))
        return self.document

    async def list_document_blocks(
        self,
        document_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> tuple[list[Block], bool, str | None]:
        self.calls.append(
            (
                "list_blocks",
                (document_id,),
                {"page_size": page_size, "page_token": page_token},
            )
        )
        return self.block_pages.pop(0)

    async def create_document(self, title: str) -> Document:
        self.calls.append(("create_document", (title,), {}))
        return Document.builder().document_id("doc-new").title(title).build()

    async def create_block_children(
        self,
        document_id: str,
        block_id: str,
        children: list[Block],
        *,
        index: int,
    ) -> list[Block]:
        self.calls.append(
            (
                "create_children",
                (document_id, block_id, children),
                {"index": index},
            )
        )
        if len(children) == 1 and children[0].block_type == TABLE_BLOCK_TYPE:
            table = children[0].table
            assert table is not None and table.property is not None
            cell_count = table.property.row_size * table.property.column_size  # type: ignore[operator]
            created_table = (
                Block.builder()
                .block_id("table-new")
                .block_type(TABLE_BLOCK_TYPE)
                .table(
                    Table.builder()
                    .property(table.property)
                    .cells([f"cell-{number}" for number in range(cell_count)])
                    .build()
                )
                .build()
            )
            return [created_table]
        return children

    async def delete_block_children(
        self,
        document_id: str,
        block_id: str,
        *,
        start_index: int,
        end_index: int,
    ) -> None:
        self.calls.append(
            (
                "delete_children",
                (document_id, block_id),
                {"start_index": start_index, "end_index": end_index},
            )
        )


def _text_block(block_id: str, parent_id: str, content: str) -> Block:
    return Block(
        {
            "block_id": block_id,
            "parent_id": parent_id,
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": content}}]},
        }
    )


def test_read_document_with_paginated_blocks_and_table() -> None:
    client = FakeFeishuClient()
    table_property = TableProperty.builder().row_size(2).column_size(2).header_row(True).build()
    page = Block.builder().block_id("doc1").block_type(1).build()
    heading = Block(
        {
            "block_id": "heading",
            "parent_id": "doc1",
            "block_type": 3,
            "heading1": {"elements": [{"text_run": {"content": "标题"}}]},
        }
    )
    table = (
        Block.builder()
        .block_id("table1")
        .parent_id("doc1")
        .block_type(TABLE_BLOCK_TYPE)
        .table(
            Table.builder()
            .property(table_property)
            .cells(["cell1", "cell2", "cell3", "cell4"])
            .build()
        )
        .build()
    )
    cells_and_text = []
    for number, value in enumerate(["姓名", "年龄", "小明", "18"], start=1):
        cells_and_text.extend(
            [
                Block(
                    {
                        "block_id": f"cell{number}",
                        "parent_id": "table1",
                        "block_type": 32,
                        "children": [f"text{number}"],
                        "table_cell": {},
                    }
                ),
                _text_block(f"text{number}", f"cell{number}", value),
            ]
        )
    client.block_pages = [
        ([page, heading, table], True, "next"),
        (cells_and_text, False, None),
    ]
    service = FeishuDocumentService(client, document_url_base="https://example.feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.read_document("doc1"))

    assert result.title == "示例文档"
    assert result.content == "# 标题\n| 姓名 | 年龄 |\n| --- | --- |\n| 小明 | 18 |"
    assert len(result.blocks) == 11
    assert client.calls[2][2]["page_token"] == "next"


def test_create_document_writes_markdown_table_cells() -> None:
    client = FakeFeishuClient()
    service = FeishuDocumentService(client, document_url_base="https://example.feishu.cn/docx")  # type: ignore[arg-type]
    markdown = "# 标题\n| 姓名 | 年龄 |\n| --- | --- |\n| 小明 | 18 |"

    result = asyncio.run(service.create_document("测试文档", markdown))

    assert result.document_id == "doc-new"
    assert result.url == "https://example.feishu.cn/docx/doc-new"
    create_calls = [call for call in client.calls if call[0] == "create_children"]
    assert create_calls[0][1][2][0].block_type == 3
    assert create_calls[1][1][2][0].block_type == TABLE_BLOCK_TYPE
    assert [call[1][1] for call in create_calls[2:]] == [
        "cell-0",
        "cell-1",
        "cell-2",
        "cell-3",
    ]


def test_update_document_replaces_root_children() -> None:
    client = FakeFeishuClient()
    client.block_pages = [
        (
            [
                Block.builder().block_id("doc1").block_type(1).build(),
                Block.builder()
                .block_id("old1")
                .parent_id("doc1")
                .block_type(2)
                .build(),
                Block.builder()
                .block_id("nested")
                .parent_id("old1")
                .block_type(2)
                .build(),
            ],
            False,
            None,
        )
    ]
    service = FeishuDocumentService(client, document_url_base="https://feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.update_document("doc1", "新正文"))

    assert result.updated is True
    assert result.block_count == 1
    delete_call = next(call for call in client.calls if call[0] == "delete_children")
    assert delete_call[2] == {"start_index": 0, "end_index": 1}


def test_append_document_preserves_existing_content_and_appends_table() -> None:
    client = FakeFeishuClient()
    existing_table = (
        Block.builder()
        .block_id("old-table")
        .parent_id("doc1")
        .block_type(TABLE_BLOCK_TYPE)
        .table(
            Table.builder()
            .property(TableProperty.builder().row_size(1).column_size(1).build())
            .cells(["old-cell"])
            .build()
        )
        .build()
    )
    client.block_pages = [
        (
            [
                Block.builder().block_id("doc1").block_type(1).build(),
                _text_block("old-text", "doc1", "已有正文"),
                existing_table,
                Block(
                    {
                        "block_id": "old-cell",
                        "parent_id": "old-table",
                        "block_type": 32,
                        "children": ["old-cell-text"],
                        "table_cell": {},
                    }
                ),
                _text_block("old-cell-text", "old-cell", "已有表格内容"),
            ],
            False,
            None,
        )
    ]
    service = FeishuDocumentService(client, document_url_base="https://feishu.cn/docx")  # type: ignore[arg-type]
    content = "追加正文\n| 新列 |\n| --- |\n| 新值 |"

    result = asyncio.run(service.append_document("doc1", content))

    assert result.appended is True
    assert result.block_count == 2
    assert not any(call[0] == "delete_children" for call in client.calls)
    create_calls = [call for call in client.calls if call[0] == "create_children"]
    assert create_calls[0][1][1] == "doc1"
    assert create_calls[0][2]["index"] == 2
    assert create_calls[0][1][2][0].text.elements[0].text_run.content == "追加正文"
    assert create_calls[1][2]["index"] == 3
    assert create_calls[1][1][2][0].block_type == TABLE_BLOCK_TYPE
    assert [call[1][1] for call in create_calls[2:]] == ["cell-0", "cell-1"]


def test_append_empty_content_does_not_modify_document() -> None:
    client = FakeFeishuClient()
    client.block_pages = [([], False, None)]
    service = FeishuDocumentService(client, document_url_base="https://feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.append_document("doc1", ""))

    assert result.appended is False
    assert result.block_count == 0
    assert not any(call[0] in {"create_children", "delete_children"} for call in client.calls)


def test_markdown_round_trip_for_common_blocks() -> None:
    markdown = "# 标题\n普通 **粗体** 和 `代码`\n- [x] 完成\n> 引用\n---"
    parsed = markdown_to_blocks(markdown)

    assert [item.block.block_type for item in parsed] == [3, 2, 17, 15, 22]
    assert blocks_to_markdown([item.block for item in parsed]) == markdown


def test_markdown_table_is_parsed_to_table_block() -> None:
    parsed = markdown_to_blocks("| A | B |\n| --- | :---: |\n| 1 | 2 |")

    assert len(parsed) == 1
    assert parsed[0].block.block_type == TABLE_BLOCK_TYPE
    assert parsed[0].block.table.property.row_size == 2  # type: ignore[union-attr]
    assert parsed[0].block.table.property.column_size == 2  # type: ignore[union-attr]
    assert parsed[0].table_cells == ["A", "B", "1", "2"]
