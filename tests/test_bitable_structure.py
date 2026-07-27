"""Bitable 公式字段、视图和仪表盘模板的纯 Mock 测试。"""

import asyncio

import pytest
from lark_oapi.api.bitable.v1 import (
    AppDashboard,
    AppTableField,
    AppTableFieldProperty,
    AppTableView,
)

from feishu_mcp.feishu.bitable_structure import FeishuBitableStructureService
from feishu_mcp.feishu.errors import BitableValidationError


class FakeStructureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def create_bitable_formula_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        formula_expression: str,
    ) -> AppTableField:
        self.calls.append(
            (
                "create_formula_field",
                (app_token, table_id, field_name, formula_expression),
            )
        )
        property_ = (
            AppTableFieldProperty.builder()
            .formula_expression(formula_expression)
            .build()
        )
        return (
            AppTableField.builder()
            .field_id("fld_formula")
            .field_name(field_name)
            .type(20)
            .property(property_)
            .build()
        )

    async def create_bitable_view(
        self,
        app_token: str,
        table_id: str,
        view_name: str,
        view_type: str,
    ) -> AppTableView:
        self.calls.append(
            ("create_view", (app_token, table_id, view_name, view_type))
        )
        return (
            AppTableView.builder()
            .view_id("vew1")
            .view_name(view_name)
            .view_type(view_type)
            .build()
        )

    async def list_bitable_dashboards(
        self,
        app_token: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> tuple[list[AppDashboard], bool, str | None, int | None]:
        self.calls.append(
            ("list_dashboards", (app_token, page_size, page_token))
        )
        dashboard = AppDashboard.builder().block_id("blk1").name("模板仪表盘").build()
        return [dashboard], True, "next", 2

    async def copy_bitable_dashboard(
        self,
        app_token: str,
        block_id: str,
        name: str,
    ) -> tuple[str, str]:
        self.calls.append(("copy_dashboard", (app_token, block_id, name)))
        return "blk_copy", name


def test_create_formula_field_preserves_expression() -> None:
    client = FakeStructureClient()
    service = FeishuBitableStructureService(client)  # type: ignore[arg-type]

    result = asyncio.run(
        service.create_formula_field("app1", "tbl1", "总价", "[数量]*[单价]")
    )

    assert result.field_id == "fld_formula"
    assert result.field_name == "总价"
    assert result.formula_expression == "[数量]*[单价]"
    assert client.calls == [
        ("create_formula_field", ("app1", "tbl1", "总价", "[数量]*[单价]"))
    ]


def test_create_view_normalizes_supported_type() -> None:
    client = FakeStructureClient()
    service = FeishuBitableStructureService(client)  # type: ignore[arg-type]

    result = asyncio.run(service.create_view("app1", "tbl1", "任务看板", "KANBAN"))

    assert result.view_id == "vew1"
    assert result.view_type == "kanban"
    assert client.calls == [
        ("create_view", ("app1", "tbl1", "任务看板", "kanban"))
    ]


def test_list_and_copy_dashboard_template() -> None:
    client = FakeStructureClient()
    service = FeishuBitableStructureService(client)  # type: ignore[arg-type]

    dashboards = asyncio.run(
        service.list_dashboards("app1", page_size=50, page_token="current")
    )
    copied = asyncio.run(
        service.copy_dashboard("app1", "blk1", "新仪表盘")
    )

    assert dashboards.dashboards[0].block_id == "blk1"
    assert dashboards.has_more is True
    assert dashboards.page_token == "next"
    assert dashboards.total == 2
    assert copied.source_block_id == "blk1"
    assert copied.block_id == "blk_copy"
    assert copied.name == "新仪表盘"
    assert client.calls == [
        ("list_dashboards", ("app1", 50, "current")),
        ("copy_dashboard", ("app1", "blk1", "新仪表盘")),
    ]


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ("formula", "公式表达式不能为空"),
        ("view", "不支持的 Bitable 视图类型"),
    ],
)
def test_invalid_structure_input_is_rejected_before_sdk_call(
    operation: str,
    message: str,
) -> None:
    client = FakeStructureClient()
    service = FeishuBitableStructureService(client)  # type: ignore[arg-type]

    with pytest.raises(BitableValidationError, match=message):
        if operation == "formula":
            asyncio.run(service.create_formula_field("app1", "tbl1", "总价", "   "))
        else:
            asyncio.run(service.create_view("app1", "tbl1", "未知视图", "unknown"))

    assert client.calls == []
