"""文档业务与 Markdown 转换测试，全部使用内存 fake client。"""

import asyncio
from typing import Any

from feishu_mcp.feishu.document import (
    FeishuDocumentService,
    blocks_to_markdown,
    markdown_to_blocks,
)


class FakeFeishuClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_read_document_with_paginated_blocks() -> None:
    client = FakeFeishuClient(
        [
            {"document": {"document_id": "doc1", "title": "示例文档"}},
            {
                "items": [
                    {"block_id": "doc1", "block_type": 1, "page": {}},
                    {
                        "block_id": "b1",
                        "parent_id": "doc1",
                        "block_type": 3,
                        "heading1": {
                            "elements": [{"text_run": {"content": "标题", "text_element_style": {}}}]
                        },
                    },
                ],
                "has_more": True,
                "page_token": "next",
            },
            {
                "items": [
                    {
                        "block_id": "b2",
                        "parent_id": "doc1",
                        "block_type": 2,
                        "text": {
                            "elements": [
                                {
                                    "text_run": {
                                        "content": "正文",
                                        "text_element_style": {"bold": True},
                                    }
                                }
                            ]
                        },
                    }
                ],
                "has_more": False,
            },
        ]
    )
    service = FeishuDocumentService(client, document_url_base="https://example.feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.read_document("doc1"))

    assert result.title == "示例文档"
    assert result.content == "# 标题\n**正文**"
    assert len(result.blocks) == 3
    assert client.calls[2][2]["params"]["page_token"] == "next"


def test_create_document_and_write_markdown() -> None:
    client = FakeFeishuClient([{"document": {"document_id": "doc-new"}}, {}])
    service = FeishuDocumentService(client, document_url_base="https://example.feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.create_document("测试文档", "# 标题\n- 项目"))

    assert result.document_id == "doc-new"
    assert result.url == "https://example.feishu.cn/docx/doc-new"
    assert client.calls[0] == ("POST", "/open-apis/docx/v1/documents", {"json": {"title": "测试文档"}})
    children = client.calls[1][2]["json"]["children"]
    assert [block["block_type"] for block in children] == [3, 12]


def test_update_document_replaces_root_children() -> None:
    client = FakeFeishuClient(
        [
            {
                "items": [
                    {"block_id": "doc1", "block_type": 1},
                    {"block_id": "old1", "parent_id": "doc1", "block_type": 2},
                    {"block_id": "nested", "parent_id": "old1", "block_type": 2},
                ],
                "has_more": False,
            },
            {},
            {},
        ]
    )
    service = FeishuDocumentService(client, document_url_base="https://feishu.cn/docx")  # type: ignore[arg-type]

    result = asyncio.run(service.update_document("doc1", "新正文"))

    assert result.updated is True
    assert result.block_count == 1
    delete_call = client.calls[1]
    assert delete_call[0] == "DELETE"
    assert delete_call[2]["json"] == {"start_index": 0, "end_index": 1}
    assert client.calls[2][2]["json"]["children"][0]["block_type"] == 2


def test_markdown_round_trip_for_common_blocks() -> None:
    markdown = "# 标题\n普通 **粗体** 和 `代码`\n- [x] 完成\n> 引用\n---"
    blocks = markdown_to_blocks(markdown)

    assert [block["block_type"] for block in blocks] == [3, 2, 17, 15, 22]
    assert blocks_to_markdown(blocks) == markdown
