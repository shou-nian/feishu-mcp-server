"""飞书 Docx 文档业务封装与 Markdown 转换。"""

import re
from typing import Any

from feishu_mcp.feishu.client import FeishuClient
from feishu_mcp.feishu.errors import FeishuAPIError
from feishu_mcp.models.schemas import CreateDocumentResult, DocumentResult, UpdateDocumentResult

DOCUMENTS_PATH = "/open-apis/docx/v1/documents"
BLOCK_PAGE_SIZE = 500
INSERT_BATCH_SIZE = 50

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


class FeishuDocumentService:
    """提供读取、创建和全量替换文档正文的高层接口。"""

    def __init__(self, client: FeishuClient, *, document_url_base: str) -> None:
        self._client = client
        self._document_url_base = document_url_base.rstrip("/")

    async def read_document(self, document_id: str) -> DocumentResult:
        """读取标题和全部 blocks，并转换为 Markdown。"""

        metadata = await self._client.request("GET", f"{DOCUMENTS_PATH}/{document_id}")
        document = metadata.get("document", {})
        title = document.get("title", "") if isinstance(document, dict) else ""
        blocks = await self._list_blocks(document_id)
        return DocumentResult(
            document_id=document_id,
            title=str(title),
            content=blocks_to_markdown(blocks),
            blocks=blocks,
        )

    async def create_document(self, title: str, content: str) -> CreateDocumentResult:
        """创建文档，并将 Markdown 正文写入根 block。"""

        data = await self._client.request("POST", DOCUMENTS_PATH, json={"title": title})
        document = data.get("document", {})
        document_id = document.get("document_id") if isinstance(document, dict) else None
        if not isinstance(document_id, str) or not document_id:
            raise FeishuAPIError("飞书创建文档成功，但响应中缺少 document_id")

        blocks = markdown_to_blocks(content)
        await self._insert_blocks(document_id, blocks)
        return CreateDocumentResult(
            document_id=document_id,
            url=f"{self._document_url_base}/{document_id}",
        )

    async def update_document(self, document_id: str, content: str) -> UpdateDocumentResult:
        """删除根 block 下的旧正文，再写入 Markdown 转换后的新正文。"""

        existing_blocks = await self._list_blocks(document_id)
        root_children = [
            block
            for block in existing_blocks
            if block.get("block_id") != document_id and block.get("parent_id") == document_id
        ]
        if root_children:
            await self._client.request(
                "DELETE",
                f"{DOCUMENTS_PATH}/{document_id}/blocks/{document_id}/children/batch_delete",
                json={"start_index": 0, "end_index": len(root_children)},
            )

        blocks = markdown_to_blocks(content)
        await self._insert_blocks(document_id, blocks)
        return UpdateDocumentResult(document_id=document_id, block_count=len(blocks))

    async def _list_blocks(self, document_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": BLOCK_PAGE_SIZE}
            if page_token:
                params["page_token"] = page_token
            data = await self._client.request(
                "GET",
                f"{DOCUMENTS_PATH}/{document_id}/blocks",
                params=params,
            )
            items = data.get("items", [])
            if not isinstance(items, list):
                raise FeishuAPIError("飞书文档 blocks 响应格式不正确")
            blocks.extend(item for item in items if isinstance(item, dict))

            if not data.get("has_more"):
                break
            next_token = data.get("page_token")
            if not isinstance(next_token, str) or not next_token:
                raise FeishuAPIError("飞书文档 blocks 分页响应缺少 page_token")
            page_token = next_token

        return blocks

    async def _insert_blocks(self, document_id: str, blocks: list[dict[str, Any]]) -> None:
        for index in range(0, len(blocks), INSERT_BATCH_SIZE):
            chunk = blocks[index : index + INSERT_BATCH_SIZE]
            await self._client.request(
                "POST",
                f"{DOCUMENTS_PATH}/{document_id}/blocks/{document_id}/children",
                json={"children": chunk, "index": index},
            )


def markdown_to_blocks(content: str) -> list[dict[str, Any]]:
    """将常用 Markdown 块转换为飞书 Docx blocks。"""

    blocks: list[dict[str, Any]] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_code_block = False
    code_lines: list[str] = []

    for line in lines:
        if line.startswith("```"):
            if in_code_block:
                blocks.append(_text_block(14, "code", "\n".join(code_lines), inline=False))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        blocks.append(_markdown_line_to_block(line))

    if in_code_block:
        blocks.append(_text_block(14, "code", "\n".join(code_lines), inline=False))

    # 空字符串表示空正文，不需要创建一个空段落。
    if content == "":
        return []
    return blocks


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """将飞书常见文本 blocks 转换为结构化 Markdown。"""

    lines: list[str] = []
    for block in blocks:
        block_type = block.get("block_type")
        if block_type in (1, None):
            continue
        if block_type == 22:
            lines.append("---")
            continue

        property_name = BLOCK_PROPERTY_BY_TYPE.get(block_type)
        if property_name is None:
            continue
        body = block.get(property_name, {})
        if not isinstance(body, dict):
            continue
        text = _elements_to_markdown(body.get("elements", []))

        if isinstance(block_type, int) and 3 <= block_type <= 11:
            lines.append(f"{'#' * (block_type - 2)} {text}")
        elif block_type == 12:
            lines.append(f"- {text}")
        elif block_type == 13:
            lines.append(f"1. {text}")
        elif block_type == 14:
            lines.append(f"```\n{text}\n```")
        elif block_type == 15:
            lines.append(f"> {text}")
        elif block_type == 17:
            checked = body.get("style", {}).get("done", False)
            lines.append(f"- [{'x' if checked else ' '}] {text}")
        else:
            lines.append(text)

    return "\n".join(lines)


def _markdown_line_to_block(line: str) -> dict[str, Any]:
    heading = re.match(r"^(#{1,9})\s+(.*)$", line)
    if heading:
        level = len(heading.group(1))
        return _text_block(level + 2, f"heading{level}", heading.group(2))
    if re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", line):
        return {"block_type": 22, "divider": {}}
    todo = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", line)
    if todo:
        return _text_block(
            17,
            "todo",
            todo.group(2),
            extra={"style": {"done": todo.group(1).lower() == "x"}},
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
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"elements": _inline_elements(text) if inline else [_text_run(text)]}
    if extra:
        body.update(extra)
    return {"block_type": block_type, property_name: body}


def _inline_elements(text: str) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    position = 0
    for match in INLINE_PATTERN.finditer(text):
        if match.start() > position:
            elements.append(_text_run(text[position : match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            elements.append(_text_run(token[2:-2], {"bold": True}))
        elif token.startswith("~~"):
            elements.append(_text_run(token[2:-2], {"strikethrough": True}))
        elif token.startswith("`"):
            elements.append(_text_run(token[1:-1], {"inline_code": True}))
        else:
            link = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", token)
            if link:
                elements.append(_text_run(link.group(1), {"link": {"url": link.group(2)}}))
        position = match.end()
    if position < len(text) or not elements:
        elements.append(_text_run(text[position:]))
    return elements


def _text_run(content: str, style: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"text_run": {"content": content, "text_element_style": style or {}}}


def _elements_to_markdown(elements: Any) -> str:
    if not isinstance(elements, list):
        return ""
    output: list[str] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        text_run = element.get("text_run")
        if isinstance(text_run, dict):
            text = str(text_run.get("content", ""))
            style = text_run.get("text_element_style", {})
            if isinstance(style, dict):
                link = style.get("link")
                if isinstance(link, dict) and link.get("url"):
                    text = f"[{text}]({link['url']})"
                if style.get("inline_code"):
                    text = f"`{text}`"
                if style.get("strikethrough"):
                    text = f"~~{text}~~"
                if style.get("bold"):
                    text = f"**{text}**"
            output.append(text)
            continue
        equation = element.get("equation")
        if isinstance(equation, dict):
            output.append(f"${equation.get('content', '')}$")
    return "".join(output)
