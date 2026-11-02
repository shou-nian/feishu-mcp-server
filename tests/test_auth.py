"""飞书官方 SDK Client 的纯 Mock 测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from lark_oapi.api.bitable.v1 import (
    AppDashboard,
    AppTableField,
    AppTableFieldForList,
    AppTableFieldProperty,
    AppTableRecord,
    AppTableView,
)
from lark_oapi.api.docx.v1 import Block, Document, Text
from lark_oapi.api.wiki.v2 import Node
from lark_oapi.core.exception import ObtainAccessTokenException
from lark_oapi.core.model import RequestOption

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
    app_table_field = SimpleNamespace(
        alist=methods.get("list_bitable_fields", AsyncMock()),
        acreate=methods.get("create_bitable_formula_field", AsyncMock()),
    )
    app_table_record = SimpleNamespace(
        acreate=methods.get("create_bitable_record", AsyncMock()),
        alist=methods.get("list_bitable_records", AsyncMock()),
        aupdate=methods.get("update_bitable_record", AsyncMock()),
    )
    app_table_view = SimpleNamespace(acreate=methods.get("create_bitable_view", AsyncMock()))
    app_dashboard = SimpleNamespace(
        alist=methods.get("list_bitable_dashboards", AsyncMock()),
        acopy=methods.get("copy_bitable_dashboard", AsyncMock()),
    )
    wiki_space = SimpleNamespace(aget_node=methods.get("resolve_wiki_document", AsyncMock()))
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
                app_table_view=app_table_view,
                app_dashboard=app_dashboard,
            )
        ),
        wiki=SimpleNamespace(v2=SimpleNamespace(space=wiki_space)),
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
    assert config.oauth_base_url == "https://accounts.feishu.cn"
    assert config.timeout == 8
    assert config.enable_set_token is False


def test_user_mode_client_enables_request_token_override() -> None:
    settings = Settings(  # type: ignore[call-arg]
        FEISHU_APP_ID="cli_test",
        FEISHU_APP_SECRET="secret",
        FEISHU_AUTH_MODE="user",
        _env_file=None,
    )

    client = FeishuClient.from_settings(settings)
    config = client._sdk_client._config  # type: ignore[attr-defined]

    assert config.enable_set_token is True
    assert client._auth_mode == "user"
    assert client._option_provider is not None


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
    assert sdk_call.await_args.args[1] is None


def test_user_access_token_is_passed_to_sdk_request() -> None:
    sdk_call = AsyncMock(
        return_value=_response(
            SimpleNamespace(document=Document.builder().document_id("doc1").title("标题").build())
        )
    )

    async def option_provider() -> RequestOption:
        return RequestOption.builder().user_access_token("u-test-token").build()

    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(get_document=sdk_call),
        option_provider=option_provider,
        auth_mode="user",
    )

    asyncio.run(client.get_document("doc1"))

    option = sdk_call.await_args.args[1]
    assert option.user_access_token == "u-test-token"


def test_docx_url_is_resolved_without_api_call() -> None:
    client = FeishuClient(_sdk_client())  # type: ignore[arg-type]

    result = asyncio.run(
        client.resolve_document_id("https://example.feishu.cn/docx/doccnExample?from=share")
    )

    assert result == "doccnExample"


def test_wiki_url_is_resolved_to_docx_token_with_user_option() -> None:
    node = (
        Node.builder()
        .node_token("wikcnExample")
        .obj_token("doccnResolved")
        .obj_type("docx")
        .build()
    )
    wiki_call = AsyncMock(return_value=_response(SimpleNamespace(node=node)))

    async def option_provider() -> RequestOption:
        return RequestOption.builder().user_access_token("u-wiki-token").build()

    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(resolve_wiki_document=wiki_call),
        option_provider=option_provider,
        auth_mode="user",
    )

    result = asyncio.run(client.resolve_document_id("https://example.feishu.cn/wiki/wikcnExample"))

    assert result == "doccnResolved"
    request = wiki_call.await_args.args[0]
    option = wiki_call.await_args.args[1]
    assert request.token == "wikcnExample"
    assert option.user_access_token == "u-wiki-token"


def test_non_docx_wiki_node_is_rejected() -> None:
    node = (
        Node.builder().node_token("wikcnSheet").obj_token("shtcnExample").obj_type("sheet").build()
    )
    wiki_call = AsyncMock(return_value=_response(SimpleNamespace(node=node)))
    client = FeishuClient(_sdk_client(resolve_wiki_document=wiki_call))  # type: ignore[arg-type]

    with pytest.raises(FeishuAPIError, match="不是 Docx 文档"):
        asyncio.run(client.resolve_document_id("https://example.feishu.cn/wiki/wikcnSheet"))


def test_list_blocks_uses_sdk_pagination() -> None:
    block = Block.builder().block_id("b1").block_type(2).build()
    sdk_call = AsyncMock(
        return_value=_response(SimpleNamespace(items=[block], has_more=True, page_token="next"))
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
    create_call = AsyncMock(return_value=_response(SimpleNamespace(children=[child])))
    delete_call = AsyncMock(return_value=_response(SimpleNamespace(document_revision_id=2)))
    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(create_children=create_call, delete_children=delete_call)
    )

    created = asyncio.run(client.create_block_children("doc1", "doc1", [child], index=3))
    asyncio.run(client.delete_block_children("doc1", "doc1", start_index=0, end_index=1))

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
    field = AppTableFieldForList.builder().field_id("fld1").field_name("标题").type(1).build()
    list_call = AsyncMock(
        return_value=_response(SimpleNamespace(items=[field], has_more=False, page_token=None))
    )
    record = AppTableRecord.builder().record_id("rec1").fields({"标题": "内容"}).build()
    create_call = AsyncMock(return_value=_response(SimpleNamespace(record=record)))
    list_record_call = AsyncMock(
        return_value=_response(
            SimpleNamespace(
                items=[record],
                has_more=True,
                page_token="next-record",
                total=2,
            )
        )
    )
    updated_record = AppTableRecord.builder().record_id("rec1").fields({"状态": "是"}).build()
    update_call = AsyncMock(return_value=_response(SimpleNamespace(record=updated_record)))
    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(
            list_bitable_fields=list_call,
            create_bitable_record=create_call,
            list_bitable_records=list_record_call,
            update_bitable_record=update_call,
        )
    )

    fields, has_more, page_token = asyncio.run(
        client.list_bitable_fields("app1", "tbl1", page_size=100)
    )
    created = asyncio.run(client.create_bitable_record("app1", "tbl1", {"标题": "内容"}))
    records, records_has_more, record_page_token, total = asyncio.run(
        client.list_bitable_records(
            "app1",
            "tbl1",
            page_size=50,
            page_token="current-page",
            filter_expression='CurrentValue.[状态]="是"',
        )
    )
    updated = asyncio.run(client.update_bitable_record("app1", "tbl1", "rec1", {"状态": "是"}))

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
    assert records == [record]
    assert records_has_more is True
    assert record_page_token == "next-record"
    assert total == 2
    record_list_request = list_record_call.await_args.args[0]
    assert record_list_request.page_size == 50
    assert record_list_request.page_token == "current-page"
    assert record_list_request.filter == 'CurrentValue.[状态]="是"'
    assert updated.fields == {"状态": "是"}
    update_request = update_call.await_args.args[0]
    assert update_request.record_id == "rec1"
    assert update_request.request_body.fields == {"状态": "是"}


def test_bitable_structure_methods_use_sdk_async_api() -> None:
    property_ = AppTableFieldProperty.builder().formula_expression("[数量]*[单价]").build()
    formula_field = (
        AppTableField.builder()
        .field_id("fld_formula")
        .field_name("总价")
        .type(20)
        .property(property_)
        .build()
    )
    formula_call = AsyncMock(return_value=_response(SimpleNamespace(field=formula_field)))
    view = AppTableView.builder().view_id("vew1").view_name("任务看板").view_type("kanban").build()
    view_call = AsyncMock(return_value=_response(SimpleNamespace(view=view)))
    dashboard = AppDashboard.builder().block_id("blk1").name("运营仪表盘").build()
    list_dashboard_call = AsyncMock(
        return_value=_response(
            SimpleNamespace(
                dashboards=[dashboard],
                has_more=True,
                page_token="next-dashboard",
                total=2,
            )
        )
    )
    copy_dashboard_call = AsyncMock(
        return_value=_response(SimpleNamespace(block_id="blk2", name="运营仪表盘副本"))
    )
    client = FeishuClient(  # type: ignore[arg-type]
        _sdk_client(
            create_bitable_formula_field=formula_call,
            create_bitable_view=view_call,
            list_bitable_dashboards=list_dashboard_call,
            copy_bitable_dashboard=copy_dashboard_call,
        )
    )

    created_field = asyncio.run(
        client.create_bitable_formula_field("app1", "tbl1", "总价", "[数量]*[单价]")
    )
    created_view = asyncio.run(client.create_bitable_view("app1", "tbl1", "任务看板", "kanban"))
    dashboards, has_more, page_token, total = asyncio.run(
        client.list_bitable_dashboards(
            "app1",
            page_size=50,
            page_token="current-dashboard",
        )
    )
    block_id, name = asyncio.run(client.copy_bitable_dashboard("app1", "blk1", "运营仪表盘副本"))

    assert created_field.field_id == "fld_formula"
    formula_request = formula_call.await_args.args[0]
    assert formula_request.request_body.type == 20
    assert formula_request.request_body.property.formula_expression == "[数量]*[单价]"
    assert created_view.view_id == "vew1"
    view_request = view_call.await_args.args[0]
    assert view_request.request_body.view_name == "任务看板"
    assert view_request.request_body.view_type == "kanban"
    assert dashboards == [dashboard]
    assert has_more is True
    assert page_token == "next-dashboard"
    assert total == 2
    list_request = list_dashboard_call.await_args.args[0]
    assert list_request.page_size == 50
    assert list_request.page_token == "current-dashboard"
    assert list_request.with_share_config is False
    assert block_id == "blk2"
    assert name == "运营仪表盘副本"
    copy_request = copy_dashboard_call.await_args.args[0]
    assert copy_request.block_id == "blk1"
    assert copy_request.request_body.name == "运营仪表盘副本"


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
