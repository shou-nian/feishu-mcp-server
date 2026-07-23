"""飞书 Docx 文档业务封装与 Markdown/Block 转换。"""

import json
import re
from dataclasses import dataclass
from typing import Any

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    Block,
    Divider,
    Link,
    Table,
    TableProperty,
    Text,
    TextElement,
    TextElementStyle,
    TextRun,
    TextStyle,
)

from feishu_mcp.feishu.client import FeishuClient
from feishu_mcp.feishu.errors import FeishuAPIError
from feishu_mcp.models.schemas import (
    AppendDocumentResult,
    CreateDocumentResult,
    DocumentResult,
    UpdateDocumentResult,
)

BLOCK_PAGE_SIZE = 500
INSERT_BATCH_SIZE = 50
TABLE_BLOCK_TYPE = 31
TABLE_CELL_BLOCK_TYPE = 32

BLOCK_PROPERTY_BY_TYPE = {
    2: "text",
    3: "heading1",
    4: "heading2",
    5: "heading3",
    6: "heading4",
    7: "heading5",
    8: "heading6",
    9: "heading7",
    10: "heading8",
    11: "heading9",
    12: "bullet",
    13: "ordered",
    14: "code",
    15: "quote",
    17: "todo",
}

INLINE_PATTERN = re.compile(
    r"(\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\[[^\]]+\]\([^)]+\))"
)
TABLE_DELIMITER = re.compile(r"^:?-{3,}:?$")


@dataclass(slots=True)
class MarkdownBlock:
    """一个待写入的根 block；表格额外携带按行展开的单元格文本。"""

    block: Block
    table_cells: list[str] | None = None


class FeishuDocumentService:
    """提供读取、创建和全量替换文档正文的高层接口。"""

    def __init__(self, client: FeishuClient, *, document_url_base: str) -> None:
        self._client = client
        self._document_url_base = document_url_base.rstrip("/")

    async def read_document(self, document_id: str) -> DocumentResult:
        """读取标题和全部 blocks，并转换为包含表格的 Markdown。"""

        document = await self._client.get_document(document_id)
        blocks = await self._list_blocks(document_id)
        return DocumentResult(
            document_id=document_id,
            title=document.title or "",
            content=blocks_to_markdown(blocks),
            blocks=[block_to_dict(block) for block in blocks],
        )

    async def create_document(self, title: str, content: str) -> CreateDocumentResult:
        """创建文档，并将 Markdown 正文（含表格）写入根 block。"""

        document = await self._client.create_document(title)
        if not document.document_id:
            raise FeishuAPIError("飞书创建文档成功，但响应中缺少 document_id")

        blocks = markdown_to_blocks(content)
        await self._insert_blocks(document.document_id, blocks)
        return CreateDocumentResult(
            document_id=document.document_id,
            url=f"{self._document_url_base}/{document.document_id}",
        )

    async def update_document(self, document_id: str, content: str) -> UpdateDocumentResult:
        """删除根 block 下的旧正文，再写入 Markdown 转换后的新正文。"""

        existing_blocks = await self._list_blocks(document_id)
        root_children = [
            block
            for block in existing_blocks
            if block.block_id != document_id and block.parent_id == document_id
        ]
        if root_children:
            await self._client.delete_block_children(
                document_id,
                document_id,
                start_index=0,
                end_index=len(root_children),
            )

        blocks = markdown_to_blocks(content)
        await self._insert_blocks(document_id, blocks)
        return UpdateDocumentResult(document_id=document_id, block_count=len(blocks))

    async def append_document(self, document_id: str, content: str) -> AppendDocumentResult:
        """在根节点末尾追加 Markdown blocks，不删除或改写任何已有内容。"""

        blocks = markdown_to_blocks(content)
        existing_blocks = await self._list_blocks(document_id)
        root_block_count = sum(
            block.block_id != document_id and block.parent_id == document_id
            for block in existing_blocks
        )
        if blocks:
            await self._insert_blocks(
                document_id,
                blocks,
                start_index=root_block_count,
            )
        return AppendDocumentResult(
            document_id=document_id,
            appended=bool(blocks),
            block_count=len(blocks),
        )

    async def _list_blocks(self, document_id: str) -> list[Block]:
        blocks: list[Block] = []
        page_token: str | None = None

        while True:
            items, has_more, next_token = await self._client.list_document_blocks(
                document_id,
                page_size=BLOCK_PAGE_SIZE,
                page_token=page_token,
            )
            blocks.extend(items)
            if not has_more:
                break
            if not next_token:
                raise FeishuAPIError("飞书文档 blocks 分页响应缺少 page_token")
            page_token = next_token

        return blocks

    async def _insert_blocks(
        self,
        document_id: str,
        blocks: list[MarkdownBlock],
        *,
        start_index: int = 0,
    ) -> None:
        root_index = start_index
        position = 0
        while position < len(blocks):
            current = blocks[position]
            if current.table_cells is not None:
                created = await self._client.create_block_children(
                    document_id,
                    document_id,
                    [current.block],
                    index=root_index,
                )
                await self._fill_table_cells(document_id, created, current.table_cells)
                position += 1
                root_index += 1
                continue

            batch: list[Block] = []
            while (
                position < len(blocks)
                and blocks[position].table_cells is None
                and len(batch) < INSERT_BATCH_SIZE
            ):
                batch.append(blocks[position].block)
                position += 1
            await self._client.create_block_children(
                document_id,
                document_id,
                batch,
                index=root_index,
            )
            root_index += len(batch)

    async def _fill_table_cells(
        self,
        document_id: str,
        created: list[Block],
        values: list[str],
    ) -> None:
        if not created or created[0].table is None:
            raise FeishuAPIError("飞书创建表格成功，但响应中缺少表格 block")
        table_block = created[0]
        cell_ids = table_block.table.cells or table_block.children or []
        if len(cell_ids) != len(values):
            raise FeishuAPIError("飞书创建表格返回的单元格数量不正确")

        for cell_id, value in zip(cell_ids, values, strict=True):
            cell_text = value.replace("<br>", "\n")
            await self._client.create_block_children(
                document_id,
                cell_id,
                [_text_block(2, "text", cell_text)],
                index=0,
            )


def markdown_to_blocks(content: str) -> list[MarkdownBlock]:
    """将常用 Markdown 块（包括标准表格）转换为官方 SDK Block。"""

    if content == "":
        return []

    blocks: list[MarkdownBlock] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(MarkdownBlock(_text_block(14, "code", "\n".join(code_lines), inline=False)))
            continue

        table = _parse_markdown_table(lines, index)
        if table is not None:
            rows, index = table
            row_size = len(rows)
            column_size = len(rows[0])
            table_property = (
                TableProperty.builder()
                .row_size(row_size)
                .column_size(column_size)
                .header_row(True)
                .build()
            )
            table_block = (
                Block.builder()
                .block_type(TABLE_BLOCK_TYPE)
                .table(Table.builder().property(table_property).build())
                .build()
            )
            blocks.append(
                MarkdownBlock(
                    block=table_block,
                    table_cells=[cell for row in rows for cell in row],
                )
            )
            continue

        blocks.append(MarkdownBlock(_markdown_line_to_block(line)))
        index += 1

    return blocks


def blocks_to_markdown(blocks: list[Block]) -> str:
    """将飞书常见文本和表格 blocks 转换为结构化 Markdown。"""

    block_index = {block.block_id: block for block in blocks if block.block_id}
    table_cell_ids = {
        block.block_id
        for block in blocks
        if block.block_type == TABLE_CELL_BLOCK_TYPE and block.block_id
    }
    lines: list[str] = []
    for block in blocks:
        if block.block_type in (1, None, TABLE_CELL_BLOCK_TYPE):
            continue
        if block.parent_id in table_cell_ids:
            continue
        if block.block_type == TABLE_BLOCK_TYPE:
            table_markdown = _table_to_markdown(block, block_index)
            if table_markdown:
                lines.append(table_markdown)
            continue
        rendered = _render_text_block(block)
        if rendered is not None:
            lines.append(rendered)

    return "\n".join(lines)


def block_to_dict(block: Block) -> dict[str, Any]:
    """将 SDK Block 转为可由 MCP 序列化的原始字典。"""

    serialized = lark.JSON.marshal(block)
    if not serialized:
        return {}
    value = json.loads(serialized)
    return value if isinstance(value, dict) else {}


def _parse_markdown_table(
    lines: list[str],
    start: int,
) -> tuple[list[list[str]], int] | None:
    if start + 1 >= len(lines) or "|" not in lines[start]:
        return None
    header = _split_table_row(lines[start])
    delimiter = _split_table_row(lines[start + 1])
    if (
        not header
        or len(header) != len(delimiter)
        or not all(TABLE_DELIMITER.fullmatch(cell.strip()) for cell in delimiter)
    ):
        return None

    rows = [header]
    position = start + 2
    while position < len(lines) and "|" in lines[position] and lines[position].strip():
        row = _split_table_row(lines[position])
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        rows.append(row[: len(header)])
        position += 1
    return rows, position


def _split_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", value)]


def _markdown_line_to_block(line: str) -> Block:
    heading = re.match(r"^(#{1,9})\s+(.*)$", line)
    if heading:
        level = len(heading.group(1))
        return _text_block(level + 2, f"heading{level}", heading.group(2))
    if re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", line):
        return Block.builder().block_type(22).divider(Divider.builder().build()).build()
    todo = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", line)
    if todo:
        return _text_block(
            17,
            "todo",
            todo.group(2),
            text_style=TextStyle.builder().done(todo.group(1).lower() == "x").build(),
        )
    bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
    if bullet:
        return _text_block(12, "bullet", bullet.group(1))
    ordered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
    if ordered:
        return _text_block(13, "ordered", ordered.group(1))
    quote = re.match(r"^\s*>\s?(.*)$", line)
    if quote:
        return _text_block(15, "quote", quote.group(1))
    return _text_block(2, "text", line)


def _text_block(
    block_type: int,
    property_name: str,
    text: str,
    *,
    inline: bool = True,
    text_style: TextStyle | None = None,
) -> Block:
    elements = _inline_elements(text) if inline else [_text_element(text)]
    text_builder = Text.builder().elements(elements)
    if text_style is not None:
        text_builder.style(text_style)
    body = text_builder.build()
    builder = Block.builder().block_type(block_type)
    getattr(builder, property_name)(body)
    return builder.build()


def _inline_elements(text: str) -> list[TextElement]:
    elements: list[TextElement] = []
    position = 0
    for match in INLINE_PATTERN.finditer(text):
        if match.start() > position:
            elements.append(_text_element(text[position : match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            style = TextElementStyle.builder().bold(True).build()
            elements.append(_text_element(token[2:-2], style))
        elif token.startswith("~~"):
            style = TextElementStyle.builder().strikethrough(True).build()
            elements.append(_text_element(token[2:-2], style))
        elif token.startswith("`"):
            style = TextElementStyle.builder().inline_code(True).build()
            elements.append(_text_element(token[1:-1], style))
        else:
            link = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", token)
            if link:
                style = (
                    TextElementStyle.builder()
                    .link(Link.builder().url(link.group(2)).build())
                    .build()
                )
                elements.append(_text_element(link.group(1), style))
        position = match.end()
    if position < len(text) or not elements:
        elements.append(_text_element(text[position:]))
    return elements


def _text_element(
    content: str,
    style: TextElementStyle | None = None,
) -> TextElement:
    run_builder = TextRun.builder().content(content)
    if style is not None:
        run_builder.text_element_style(style)
    return TextElement.builder().text_run(run_builder.build()).build()


def _render_text_block(block: Block) -> str | None:
    if block.block_type == 22:
        return "---"
    property_name = BLOCK_PROPERTY_BY_TYPE.get(block.block_type)
    if property_name is None:
        return None
    body = getattr(block, property_name, None)
    if not isinstance(body, Text):
        return None
    text = _elements_to_markdown(body.elements)

    if block.block_type is not None and 3 <= block.block_type <= 11:
        return f"{'#' * (block.block_type - 2)} {text}"
    if block.block_type == 12:
        return f"- {text}"
    if block.block_type == 13:
        return f"1. {text}"
    if block.block_type == 14:
        return f"```\n{text}\n```"
    if block.block_type == 15:
        return f"> {text}"
    if block.block_type == 17:
        checked = bool(body.style and body.style.done)
        return f"- [{'x' if checked else ' '}] {text}"
    return text


def _table_to_markdown(block: Block, block_index: dict[str, Block]) -> str:
    if block.table is None or block.table.property is None:
        return ""
    row_size = block.table.property.row_size or 0
    column_size = block.table.property.column_size or 0
    if row_size <= 0 or column_size <= 0:
        return ""
    cell_ids = block.table.cells or block.children or []
    cell_values = [_table_cell_text(cell_id, block_index) for cell_id in cell_ids]
    expected = row_size * column_size
    cell_values.extend([""] * max(0, expected - len(cell_values)))

    rows = [
        cell_values[offset : offset + column_size]
        for offset in range(0, expected, column_size)
    ]
    markdown_lines = [_format_table_row(rows[0])]
    markdown_lines.append(_format_table_row(["---"] * column_size))
    markdown_lines.extend(_format_table_row(row) for row in rows[1:])
    return "\n".join(markdown_lines)


def _table_cell_text(cell_id: str, block_index: dict[str, Block]) -> str:
    cell = block_index.get(cell_id)
    if cell is None:
        return ""
    child_ids = cell.children or [
        block_id
        for block_id, block in block_index.items()
        if block.parent_id == cell_id
    ]
    rendered = [
        text
        for child_id in child_ids
        if (child := block_index.get(child_id)) is not None
        if (text := _render_text_block(child)) is not None
    ]
    return "<br>".join(rendered).replace("|", "\\|").replace("\n", "<br>")


def _format_table_row(cells: list[str]) -> str:
    return f"| {' | '.join(cells)} |"


def _elements_to_markdown(elements: list[TextElement] | None) -> str:
    output: list[str] = []
    for element in elements or []:
        if element.text_run is not None:
            text = element.text_run.content or ""
            style = element.text_run.text_element_style
            if style is not None:
                if style.link is not None and style.link.url:
                    text = f"[{text}]({style.link.url})"
                if style.inline_code:
                    text = f"`{text}`"
                if style.strikethrough:
                    text = f"~~{text}~~"
                if style.bold:
                    text = f"**{text}**"
            output.append(text)
        elif element.equation is not None:
            output.append(f"${element.equation.content or ''}$")
    return "".join(output)
