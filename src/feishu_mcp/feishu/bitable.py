"""飞书 Bitable 字段结构查询、值校验与记录新增。"""

import json
from datetime import datetime, timezone
from typing import Any

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import AppTableFieldForList

from feishu_mcp.feishu.client import FeishuClient
from feishu_mcp.feishu.errors import BitableValidationError, FeishuAPIError
from feishu_mcp.models.schemas import (
    BitableFieldSchema,
    BitableFieldsResult,
    BitableRecordResult,
)

FIELD_PAGE_SIZE = 100
FIELD_TYPE_NAMES = {
    1: "text",
    2: "number",
    3: "single_select",
    4: "multi_select",
    5: "datetime",
    7: "checkbox",
    11: "user",
    13: "phone",
    15: "url",
    17: "attachment",
    18: "single_link",
    19: "lookup",
    20: "formula",
    21: "duplex_link",
    22: "location",
    23: "group",
    1001: "created_time",
    1002: "modified_time",
    1003: "created_user",
    1004: "modified_user",
    1005: "auto_number",
}
READ_ONLY_FIELD_TYPES = {19, 20, 1001, 1002, 1003, 1004, 1005}


class FeishuBitableService:
    """根据实时字段 schema 安全写入 Bitable 记录。"""

    def __init__(self, client: FeishuClient) -> None:
        self._client = client

    async def list_fields(self, app_token: str, table_id: str) -> BitableFieldsResult:
        fields = await self._list_all_fields(app_token, table_id)
        return BitableFieldsResult(
            app_token=app_token,
            table_id=table_id,
            fields=[_field_schema(field) for field in fields],
        )

    async def create_record(
        self,
        app_token: str,
        table_id: str,
        values: dict[str, Any],
    ) -> BitableRecordResult:
        fields = await self._list_all_fields(app_token, table_id)
        by_name = {field.field_name: field for field in fields if field.field_name}
        by_id = {field.field_id: field for field in fields if field.field_id}
        normalized: dict[str, Any] = {}

        for supplied_name, value in values.items():
            field = by_name.get(supplied_name) or by_id.get(supplied_name)
            if field is None:
                available = "、".join(sorted(by_name))
                raise BitableValidationError(
                    f"Bitable 字段不存在：{supplied_name}。可用字段：{available}"
                )
            if not field.field_name:
                raise BitableValidationError(f"Bitable 字段缺少名称：{supplied_name}")
            if not _is_writable(field):
                raise BitableValidationError(
                    f"Bitable 字段“{field.field_name}”是只读字段，不能在新增记录时写入"
                )
            normalized[field.field_name] = _normalize_field_value(field, value)

        if not normalized:
            raise BitableValidationError("新增 Bitable 记录至少需要提供一个字段值")

        record = await self._client.create_bitable_record(app_token, table_id, normalized)
        if not record.record_id:
            raise FeishuAPIError("飞书新增 Bitable 记录成功，但响应中缺少 record_id")
        return BitableRecordResult(
            app_token=app_token,
            table_id=table_id,
            record_id=record.record_id,
            fields=record.fields or normalized,
        )

    async def _list_all_fields(
        self,
        app_token: str,
        table_id: str,
    ) -> list[AppTableFieldForList]:
        fields: list[AppTableFieldForList] = []
        page_token: str | None = None
        while True:
            items, has_more, next_token = await self._client.list_bitable_fields(
                app_token,
                table_id,
                page_size=FIELD_PAGE_SIZE,
                page_token=page_token,
            )
            fields.extend(items)
            if not has_more:
                return fields
            if not next_token:
                raise FeishuAPIError("飞书 Bitable 字段分页响应缺少 page_token")
            page_token = next_token


def _field_schema(field: AppTableFieldForList) -> BitableFieldSchema:
    options = []
    if field.property and field.property.options:
        options = [option.name for option in field.property.options if option.name]
    return BitableFieldSchema(
        field_id=field.field_id or "",
        field_name=field.field_name or "",
        type=field.type or 0,
        type_name=FIELD_TYPE_NAMES.get(field.type, f"unknown_{field.type}"),
        ui_type=field.ui_type,
        is_primary=bool(field.is_primary),
        is_hidden=bool(field.is_hidden),
        writable=_is_writable(field),
        options=options,
        property=_sdk_object_to_dict(field.property),
    )


def _is_writable(field: AppTableFieldForList) -> bool:
    if field.type in READ_ONLY_FIELD_TYPES:
        return False
    if field.property and (field.property.formula_expression or field.property.auto_fill):
        return False
    return field.type in FIELD_TYPE_NAMES


def _normalize_field_value(field: AppTableFieldForList, value: Any) -> Any:
    if value is None:
        return None
    field_type = field.type
    name = field.field_name or field.field_id or "未知字段"

    if field_type == 1:
        return _require_type(name, value, str, "字符串")
    if field_type == 2:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _value_error(name, "数字")
        return value
    if field_type == 3:
        selected = _require_type(name, value, str, "选项名称字符串")
        _validate_options(field, [selected])
        return selected
    if field_type == 4:
        selected = _string_list(name, value, "选项名称数组")
        _validate_options(field, selected)
        return selected
    if field_type == 5:
        return _datetime_milliseconds(name, value)
    if field_type == 7:
        return _require_type(name, value, bool, "布尔值")
    if field_type == 11:
        return _identity_list(name, value, "人员 ID")
    if field_type == 13:
        return _require_type(name, value, str, "电话号码字符串")
    if field_type == 15:
        if isinstance(value, str):
            return {"link": value, "text": value}
        if isinstance(value, dict) and isinstance(value.get("link"), str):
            return {"link": value["link"], "text": value.get("text") or value["link"]}
        raise _value_error(name, "URL 字符串或包含 link/text 的对象")
    if field_type == 17:
        if not isinstance(value, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("file_token"), str)
            for item in value
        ):
            raise _value_error(name, "包含 file_token 的对象数组")
        return value
    if field_type in {18, 21}:
        return _string_list(name, value, "关联记录 ID 数组")
    if field_type == 22:
        if not isinstance(value, dict):
            raise _value_error(name, "地理位置对象")
        return value
    if field_type == 23:
        return _identity_list(name, value, "群组 ID")
    raise BitableValidationError(
        f"Bitable 字段“{name}”类型 {FIELD_TYPE_NAMES.get(field_type, field_type)} 暂不支持写入"
    )


def _require_type(name: str, value: Any, expected: type, description: str) -> Any:
    if not isinstance(value, expected):
        raise _value_error(name, description)
    return value


def _string_list(name: str, value: Any, description: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _value_error(name, description)
    return value


def _identity_list(name: str, value: Any, identity_name: str) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else [value]
    normalized: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, str):
            normalized.append({"id": item})
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            normalized.append({"id": item["id"]})
        else:
            raise _value_error(name, f"{identity_name}字符串或对象数组")
    return normalized


def _datetime_milliseconds(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise _value_error(name, "毫秒时间戳或 ISO 8601 日期时间字符串")
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        raise _value_error(name, "毫秒时间戳或 ISO 8601 日期时间字符串")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _value_error(name, "ISO 8601 日期时间字符串") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _validate_options(field: AppTableFieldForList, selected: list[str]) -> None:
    options = {
        option.name
        for option in (field.property.options if field.property and field.property.options else [])
        if option.name
    }
    unknown = [option for option in selected if options and option not in options]
    if unknown:
        raise BitableValidationError(
            f"Bitable 字段“{field.field_name}”包含不存在的选项：{'、'.join(unknown)}；"
            f"可用选项：{'、'.join(sorted(options))}"
        )


def _value_error(name: str, expected: str) -> BitableValidationError:
    return BitableValidationError(f"Bitable 字段“{name}”的值格式错误，期望：{expected}")


def _sdk_object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    serialized = lark.JSON.marshal(value)
    if not serialized:
        return {}
    result = json.loads(serialized)
    return result if isinstance(result, dict) else {}
