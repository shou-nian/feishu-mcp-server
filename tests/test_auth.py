"""飞书官方 SDK Client 的纯 Mock 测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from lark_oapi.api.bitable.v1 import AppTableFieldForList, AppTableRecord
from lark_oapi.api.docx.v1 import Block, Document, Text
from lark_oapi.core.exception import ObtainAccessTokenException

from feishu_mcp.config.settings import Settings
from feishu_mcp.feishu.client import FeishuClient
from feishu_mcp.feishu.errors import FeishuAPIError, FeishuAuthError


def _response(data: object = None, *, code: int = 0, msg: str = "success") -> SimpleNamespace:
    return SimpleNamespace(success=lambda: code == 0, code=code, msg=msg, data=data)


def _sdk_client(**methods: AsyncMock) -> SimpleNamespace:
    document = SimpleNamespace(
        aget=methods.get("get_document", AsyncMock()),
        acreate=methods.get("create_document", AsyncMock()),
    )
    document_block = SimpleNamespace(alist=methods.get("list_blocks", AsyncMock()))
    document_block_children = SimpleNamespace(
        acreate=methods.get("create_children", AsyncMock()),
        abatch_delete=methods.get("delete_children", AsyncMock()),
    )
    app_table_field = SimpleNamespace(alist=methods.get("list_bitable_fields", AsyncMock()))
    app_table_record = SimpleNamespace(acreate=methods.get("create_bitable_record", AsyncMock()))
    return SimpleNamespace(
        docx=SimpleNamespace(
            v1=SimpleNamespace(
                document=document,
                document_block=document_block,
                document_block_children=document_block_children,
            )
        ),
        bitable=SimpleNamespace(
            v1=SimpleNamespace(
                app_table_field=app_table_field,
                app_table_record=app_table_record,
            )
        ),
    )


def test_official_client_is_built_from_settings() -> None:
    settings = Settings(  # type: ignore[call-arg]
        FEISHU_APP_ID="cli_test",
        FEISHU_APP_SECRET="secret",
        FEISHU_REQUEST_TIMEOUT=8,
        _env_file=None,
    )

    client = FeishuClient.from_settings(settings)
    config = client._sdk_client._config  # type: ignore[attr-defined]

    assert config.app_id == "cli_test"
    assert config.app_secret == "secret"
    assert config.domain == "https://open.feishu.cn"
    assert config.timeout == 8


def test_get_document_uses_sdk_async_api() -> None:
    sdk_call = AsyncMock(
        return_value=_response(
            SimpleNamespace(document=Document.builder().document_id("doc1").title("标题").build())
        )
    )
    client = FeishuClient(_sdk_client(get_document=sdk_call))  # type: ignore[arg-type]

    result = asyncio.run(client.get_document("doc1"))

    assert result.title == "标题"
    request = sdk_call.await_args.args[0]
    assert request.document_id == "doc1"


def test_list_blocks_uses_sdk_pagination() -> None:
    block = Block.builder().block_id("b1").block_type(2).build()
    sdk_call = AsyncMock(
        return_value=_response(
            SimpleNamespace(items=[block], has_more=True, page_token="next")
        )
    )
    client = FeishuClient(_sdk_client(list_blocks=sdk_call))  # type: ignore[arg-type]

    items, has_more, token = asyncio.run(
        client.list_document_blocks("doc1", page_size=500, page_token="current")
    )

    assert items == [block]
    assert has_more is True
    assert token == "next"
    request = sdk_call.await_args.args[0]
    assert request.page_size == 500
    assert request.page_token == "current"


def test_create_and_delete_children_use_sdk_async_api() -> None:
    child = Block.builder().block_type(2).text(Text.builder().elements([]).build()).build()
    create_call = AsyncMock(
        return_value=_response(SimpleNamespace(children=[child]))
    )
    delete_call = AsyncMock(return_value=_response(SimpleNamespace(document_revision_id=2)))
    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(create_children=create_call, delete_children=delete_call)
    )

    created = asyncio.run(
        client.create_block_children("doc1", "doc1", [child], index=3)
    )
    asyncio.run(
        client.delete_block_children("doc1", "doc1", start_index=0, end_index=1)
    )

    assert created == [child]
    create_request = create_call.await_args.args[0]
    assert create_request.document_id == "doc1"
    assert create_request.block_id == "doc1"
    assert create_request.request_body.children == [child]
    assert create_request.request_body.index == 3
    delete_request = delete_call.await_args.args[0]
    assert delete_request.request_body.start_index == 0
    assert delete_request.request_body.end_index == 1


def test_bitable_field_and_record_methods_use_sdk_async_api() -> None:
    field = (
        AppTableFieldForList.builder()
        .field_id("fld1")
        .field_name("标题")
        .type(1)
        .build()
    )
    list_call = AsyncMock(
        return_value=_response(SimpleNamespace(items=[field], has_more=False, page_token=None))
    )
    record = AppTableRecord.builder().record_id("rec1").fields({"标题": "内容"}).build()
    create_call = AsyncMock(return_value=_response(SimpleNamespace(record=record)))
    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(
            list_bitable_fields=list_call,
            create_bitable_record=create_call,
        )
    )

    fields, has_more, page_token = asyncio.run(
        client.list_bitable_fields("app1", "tbl1", page_size=100)
    )
    created = asyncio.run(
        client.create_bitable_record("app1", "tbl1", {"标题": "内容"})
    )

    assert fields == [field]
    assert has_more is False
    assert page_token is None
    list_request = list_call.await_args.args[0]
    assert list_request.app_token == "app1"
    assert list_request.table_id == "tbl1"
    assert list_request.page_size == 100
    assert created.record_id == "rec1"
    create_request = create_call.await_args.args[0]
    assert create_request.request_body.fields == {"标题": "内容"}


def test_sdk_auth_error_is_user_friendly() -> None:
    sdk_call = AsyncMock(
        side_effect=ObtainAccessTokenException("obtain token failed", 99991663, "bad secret")
    )
    client = FeishuClient(_sdk_client(get_document=sdk_call))  # type: ignore[arg-type]

    with pytest.raises(FeishuAuthError, match="请检查 FEISHU_APP_ID"):
        asyncio.run(client.get_document("doc1"))


def test_sdk_api_error_is_user_friendly() -> None:
    sdk_call = AsyncMock(return_value=_response(code=1770032, msg="not found"))
    client = FeishuClient(_sdk_client(get_document=sdk_call))  # type: ignore[arg-type]

    with pytest.raises(FeishuAPIError, match="文档不存在"):
        asyncio.run(client.get_document("missing"))
