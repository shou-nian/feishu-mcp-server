"""基于飞书官方 lark-oapi SDK 的异步 Docx/Bitable Client。"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    AppTableFieldForList,
    AppTableRecord,
    CreateAppTableRecordRequest,
    ListAppTableFieldRequest,
    ListAppTableRecordRequest,
    UpdateAppTableRecordRequest,
)
from lark_oapi.api.docx.v1 import (
    BatchDeleteDocumentBlockChildrenRequest,
    BatchDeleteDocumentBlockChildrenRequestBody,
    Block,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    Document,
    GetDocumentRequest,
    ListDocumentBlockRequest,
)
from lark_oapi.core.exception import (
    AccessTokenException,
    ClientAssertionException,
    NoAuthorizationException,
    ObtainAccessTokenException,
)

from feishu_mcp.config.settings import Settings
from feishu_mcp.feishu.auth import build_lark_client
from feishu_mcp.feishu.errors import FeishuAPIError, FeishuAuthError

ERROR_MESSAGES = {
    99991663: "飞书鉴权失败，请检查 FEISHU_APP_ID 和 FEISHU_APP_SECRET",
    99991664: "飞书应用已停用，请检查应用状态",
    99991668: "飞书访问凭证已过期，请重试",
    91403: "飞书应用缺少文档权限，请在开放平台配置所需权限",
    1770032: "飞书文档不存在，或当前应用无权访问",
}
AUTH_EXCEPTIONS = (
    AccessTokenException,
    ClientAssertionException,
    NoAuthorizationException,
    ObtainAccessTokenException,
)
ResponseT = TypeVar("ResponseT")


class FeishuClient:
    """对官方 SDK Docx/Bitable v1 异步接口的业务友好封装。"""

    def __init__(self, sdk_client: lark.Client) -> None:
        self._sdk_client = sdk_client

    @classmethod
    def from_settings(cls, settings: Settings) -> "FeishuClient":
        """从应用配置创建官方 SDK 客户端。"""

        return cls(build_lark_client(settings))

    async def get_document(self, document_id: str) -> Document:
        request = GetDocumentRequest.builder().document_id(document_id).build()
        data = await self._call(lambda: self._sdk_client.docx.v1.document.aget(request))
        document = getattr(data, "document", None)
        if not isinstance(document, Document):
            raise FeishuAPIError("飞书读取文档成功，但响应中缺少 document")
        return document

    async def list_document_blocks(
        self,
        document_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> tuple[list[Block], bool, str | None]:
        builder = (
            ListDocumentBlockRequest.builder()
            .document_id(document_id)
            .page_size(page_size)
        )
        if page_token:
            builder.page_token(page_token)
        request = builder.build()
        data = await self._call(lambda: self._sdk_client.docx.v1.document_block.alist(request))
        items = getattr(data, "items", None) or []
        if not isinstance(items, list) or any(not isinstance(item, Block) for item in items):
            raise FeishuAPIError("飞书文档 blocks 响应格式不正确")
        return items, bool(getattr(data, "has_more", False)), getattr(data, "page_token", None)

    async def create_document(self, title: str) -> Document:
        body = CreateDocumentRequestBody.builder().title(title).build()
        request = CreateDocumentRequest.builder().request_body(body).build()
        data = await self._call(lambda: self._sdk_client.docx.v1.document.acreate(request))
        document = getattr(data, "document", None)
        if not isinstance(document, Document):
            raise FeishuAPIError("飞书创建文档成功，但响应中缺少 document")
        return document

    async def create_block_children(
        self,
        document_id: str,
        block_id: str,
        children: list[Block],
        *,
        index: int,
    ) -> list[Block]:
        body = (
            CreateDocumentBlockChildrenRequestBody.builder()
            .children(children)
            .index(index)
            .build()
        )
        request = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(block_id)
            .request_body(body)
            .build()
        )
        data = await self._call(
            lambda: self._sdk_client.docx.v1.document_block_children.acreate(request)
        )
        created = getattr(data, "children", None) or []
        if not isinstance(created, list) or any(not isinstance(item, Block) for item in created):
            raise FeishuAPIError("飞书创建 blocks 响应格式不正确")
        return created

    async def delete_block_children(
        self,
        document_id: str,
        block_id: str,
        *,
        start_index: int,
        end_index: int,
    ) -> None:
        body = (
            BatchDeleteDocumentBlockChildrenRequestBody.builder()
            .start_index(start_index)
            .end_index(end_index)
            .build()
        )
        request = (
            BatchDeleteDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(block_id)
            .request_body(body)
            .build()
        )
        await self._call(
            lambda: self._sdk_client.docx.v1.document_block_children.abatch_delete(request)
        )

    async def list_bitable_fields(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> tuple[list[AppTableFieldForList], bool, str | None]:
        builder = (
            ListAppTableFieldRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(page_size)
        )
        if page_token:
            builder.page_token(page_token)
        request = builder.build()
        data = await self._call(
            lambda: self._sdk_client.bitable.v1.app_table_field.alist(request)
        )
        items = getattr(data, "items", None) or []
        if not isinstance(items, list) or any(
            not isinstance(item, AppTableFieldForList) for item in items
        ):
            raise FeishuAPIError("飞书 Bitable 字段响应格式不正确")
        return items, bool(getattr(data, "has_more", False)), getattr(data, "page_token", None)

    async def create_bitable_record(
        self,
        app_token: str,
        table_id: str,
        fields: dict[str, Any],
    ) -> AppTableRecord:
        record = AppTableRecord.builder().fields(fields).build()
        request = (
            CreateAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .request_body(record)
            .build()
        )
        data = await self._call(
            lambda: self._sdk_client.bitable.v1.app_table_record.acreate(request)
        )
        created = getattr(data, "record", None)
        if not isinstance(created, AppTableRecord):
            raise FeishuAPIError("飞书新增 Bitable 记录成功，但响应中缺少 record")
        return created

    async def list_bitable_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int,
        page_token: str | None = None,
        filter_expression: str | None = None,
    ) -> tuple[list[AppTableRecord], bool, str | None, int | None]:
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(page_size)
        )
        if page_token:
            builder.page_token(page_token)
        if filter_expression:
            builder.filter(filter_expression)
        request = builder.build()
        data = await self._call(
            lambda: self._sdk_client.bitable.v1.app_table_record.alist(request)
        )
        items = getattr(data, "items", None) or []
        if not isinstance(items, list) or any(
            not isinstance(item, AppTableRecord) for item in items
        ):
            raise FeishuAPIError("飞书 Bitable 记录响应格式不正确")
        total = getattr(data, "total", None)
        return (
            items,
            bool(getattr(data, "has_more", False)),
            getattr(data, "page_token", None),
            total if isinstance(total, int) else None,
        )

    async def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> AppTableRecord:
        record = AppTableRecord.builder().fields(fields).build()
        request = (
            UpdateAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .record_id(record_id)
            .request_body(record)
            .build()
        )
        data = await self._call(
            lambda: self._sdk_client.bitable.v1.app_table_record.aupdate(request)
        )
        updated = getattr(data, "record", None)
        if not isinstance(updated, AppTableRecord):
            raise FeishuAPIError("飞书更新 Bitable 记录成功，但响应中缺少 record")
        return updated

    async def _call(self, operation: Callable[[], Awaitable[ResponseT]]) -> Any:
        try:
            response = await operation()
        except AUTH_EXCEPTIONS as exc:
            raise FeishuAuthError(
                "飞书鉴权失败，请检查 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            ) from exc
        except Exception as exc:
            raise FeishuAPIError("飞书官方 SDK 请求失败，请检查网络后重试") from exc

        if not response.success():  # type: ignore[attr-defined]
            code = getattr(response, "code", None)
            message = ERROR_MESSAGES.get(code)
            if message is None:
                detail = getattr(response, "msg", None) or "未知错误"
                message = f"飞书 API 调用失败（code={code}）：{detail}"
            raise FeishuAPIError(message, code=code if isinstance(code, int) else None)

        data = getattr(response, "data", None)
        if data is None:
            raise FeishuAPIError("飞书 API 响应缺少 data")
        return data
