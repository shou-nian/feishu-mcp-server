"""Bitable 字段/记录查询、类型校验和记录写入测试。"""

import asyncio
from typing import Any

import pytest
from lark_oapi.api.bitable.v1 import (
    AppTableFieldForList,
    AppTableFieldProperty,
    AppTableFieldPropertyOption,
    AppTableRecord,
)

from feishu_mcp.feishu.bitable import FeishuBitableService
from feishu_mcp.feishu.errors import BitableValidationError


def _field(
    name: str,
    field_type: int,
    *,
    field_id: str | None = None,
    options: list[str] | None = None,
) -> AppTableFieldForList:
    property_builder = AppTableFieldProperty.builder()
    if options is not None:
        property_builder.options(
            [
                AppTableFieldPropertyOption.builder().id(f"opt{index}").name(option).build()
                for index, option in enumerate(options)
            ]
        )
    return (
        AppTableFieldForList.builder()
        .field_id(field_id or f"fld_{field_type}_{name}")
        .field_name(name)
        .type(field_type)
        .property(property_builder.build())
        .build()
    )


class FakeBitableClient:
    def __init__(
        self,
        pages: list[tuple[list[AppTableFieldForList], bool, str | None]],
        *,
        record_page: tuple[list[AppTableRecord], bool, str | None, int | None] | None = None,
    ) -> None:
        self.pages = pages
        self.record_page = record_page
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.created_fields: dict[str, Any] | None = None
        self.updated_fields: dict[str, Any] | None = None
        self.updated_record_id: str | None = None

    async def list_bitable_fields(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> tuple[list[AppTableFieldForList], bool, str | None]:
        self.calls.append(
            (
                "list_fields",
                (app_token, table_id),
                {"page_size": page_size, "page_token": page_token},
            )
        )
        return self.pages.pop(0)

    async def create_bitable_record(
        self,
        app_token: str,
        table_id: str,
        fields: dict[str, Any],
    ) -> AppTableRecord:
        self.calls.append(("create_record", (app_token, table_id), {"fields": fields}))
        self.created_fields = fields
        return AppTableRecord.builder().record_id("rec_new").fields(fields).build()

    async def list_bitable_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
        filter_expression: str | None = None,
    ) -> tuple[list[AppTableRecord], bool, str | None, int | None]:
        self.calls.append(
            (
                "list_records",
                (app_token, table_id),
                {
                    "page_size": page_size,
                    "page_token": page_token,
                    "filter_expression": filter_expression,
                },
            )
        )
        assert self.record_page is not None
        return self.record_page

    async def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> AppTableRecord:
        self.calls.append(
            (
                "update_record",
                (app_token, table_id, record_id),
                {"fields": fields},
            )
        )
        self.updated_record_id = record_id
        self.updated_fields = fields
        return AppTableRecord.builder().record_id(record_id).fields(fields).build()


def test_list_fields_paginates_and_returns_schema() -> None:
    client = FakeBitableClient(
        [
            ([_field("标题", 1, field_id="fld_text")], True, "next"),
            ([_field("状态", 3, options=["进行中", "完成"])], False, None),
        ]
    )
    service = FeishuBitableService(client)  # type: ignore[arg-type]

    result = asyncio.run(service.list_fields("app1", "tbl1"))

    assert [field.field_name for field in result.fields] == ["标题", "状态"]
    assert result.fields[0].type_name == "text"
    assert result.fields[0].writable is True
    assert result.fields[1].options == ["进行中", "完成"]
    assert client.calls[1][2]["page_token"] == "next"


def test_create_record_normalizes_values_using_live_schema() -> None:
    fields = [
        _field("标题", 1),
        _field("数量", 2),
        _field("状态", 3, options=["进行中", "完成"]),
        _field("标签", 4, options=["重要", "普通"]),
        _field("日期", 5),
        _field("完成", 7),
        _field("负责人", 11, field_id="fld_owner"),
        _field("链接", 15),
    ]
    client = FakeBitableClient([(fields, False, None)])
    service = FeishuBitableService(client)  # type: ignore[arg-type]

    result = asyncio.run(
        service.create_record(
            "app1",
            "tbl1",
            {
                "标题": "新任务",
                "数量": 3,
                "状态": "进行中",
                "标签": ["重要"],
                "日期": "2026-07-23T00:00:00Z",
                "完成": False,
                "fld_owner": "ou_owner",
                "链接": "https://example.com",
            },
        )
    )

    assert result.record_id == "rec_new"
    assert client.created_fields == {
        "标题": "新任务",
        "数量": 3,
        "状态": "进行中",
        "标签": ["重要"],
        "日期": 1784764800000,
        "完成": False,
        "负责人": [{"id": "ou_owner"}],
        "链接": {"link": "https://example.com", "text": "https://example.com"},
    }


def test_list_records_returns_record_ids_and_pagination() -> None:
    record = (
        AppTableRecord.builder()
        .record_id("rec_target")
        .fields({"标题": "目标行", "状态": "是"})
        .created_time(1000)
        .last_modified_time(2000)
        .record_url("https://example.feishu.cn/base/record")
        .build()
    )
    client = FakeBitableClient(
        [],
        record_page=([record], True, "next-record-page", 2),
    )
    service = FeishuBitableService(client)  # type: ignore[arg-type]

    result = asyncio.run(
        service.list_records(
            "app1",
            "tbl1",
            page_size=50,
            page_token="current-page",
            filter_expression='CurrentValue.[标题]="目标行"',
        )
    )

    assert result.records[0].record_id == "rec_target"
    assert result.records[0].fields == {"标题": "目标行", "状态": "是"}
    assert result.records[0].last_modified_time == 2000
    assert result.has_more is True
    assert result.page_token == "next-record-page"
    assert result.total == 2
    assert client.calls == [
        (
            "list_records",
            ("app1", "tbl1"),
            {
                "page_size": 50,
                "page_token": "current-page",
                "filter_expression": 'CurrentValue.[标题]="目标行"',
            },
        )
    ]


def test_update_record_selects_single_and_multi_options_by_name() -> None:
    fields = [
        _field("是否启用", 3, options=["是", "否"]),
        _field("适用范围", 4, options=["内部", "外部", "测试"]),
    ]
    client = FakeBitableClient([(fields, False, None)])
    service = FeishuBitableService(client)  # type: ignore[arg-type]

    result = asyncio.run(
        service.update_record(
            "app1",
            "tbl1",
            "rec_target",
            {"是否启用": "是", "适用范围": ["内部", "测试"]},
        )
    )

    assert result.record_id == "rec_target"
    assert client.updated_record_id == "rec_target"
    assert client.updated_fields == {
        "是否启用": "是",
        "适用范围": ["内部", "测试"],
    }


def test_update_record_rejects_unknown_select_option_before_api_call() -> None:
    client = FakeBitableClient(
        [([_field("是否启用", 3, options=["是", "否"])], False, None)]
    )
    service = FeishuBitableService(client)  # type: ignore[arg-type]

    with pytest.raises(BitableValidationError, match="不存在的选项"):
        asyncio.run(
            service.update_record(
                "app1",
                "tbl1",
                "rec_target",
                {"是否启用": "未知"},
            )
        )

    assert client.updated_fields is None


@pytest.mark.parametrize(
    ("field", "values", "message"),
    [
        (_field("公式", 20), {"公式": "1+1"}, "只读字段"),
        (_field("状态", 3, options=["完成"]), {"状态": "不存在"}, "不存在的选项"),
        (_field("数量", 2), {"数量": "三"}, "值格式错误"),
    ],
)
def test_create_record_rejects_invalid_field_values(
    field: AppTableFieldForList,
    values: dict[str, Any],
    message: str,
) -> None:
    service = FeishuBitableService(  # type: ignore[arg-type]
        FakeBitableClient([([field], False, None)])
    )

    with pytest.raises(BitableValidationError, match=message):
        asyncio.run(service.create_record("app1", "tbl1", values))


def test_create_record_rejects_unknown_field() -> None:
    service = FeishuBitableService(  # type: ignore[arg-type]
        FakeBitableClient([([_field("标题", 1)], False, None)])
    )

    with pytest.raises(BitableValidationError, match="字段不存在"):
        asyncio.run(service.create_record("app1", "tbl1", {"未知字段": "值"}))
