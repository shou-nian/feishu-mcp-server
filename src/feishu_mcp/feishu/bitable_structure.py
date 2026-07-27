"""飞书 Bitable 公式字段、视图和仪表盘模板业务。"""

from feishu_mcp.feishu.client import BITABLE_FORMULA_FIELD_TYPE, FeishuClient
from feishu_mcp.feishu.errors import BitableValidationError, FeishuAPIError
from feishu_mcp.models.schemas import (
    BitableDashboardCopyResult,
    BitableDashboardSchema,
    BitableDashboardsResult,
    BitableFormulaFieldResult,
    BitableViewResult,
)

SUPPORTED_VIEW_TYPES = {"form", "gallery", "gantt", "grid", "kanban"}


class FeishuBitableStructureService:
    """创建 Bitable 结构，并通过官方复制接口复用仪表盘组件。"""

    def __init__(self, client: FeishuClient) -> None:
        self._client = client

    async def create_formula_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        formula_expression: str,
    ) -> BitableFormulaFieldResult:
        if not formula_expression.strip():
            raise BitableValidationError("Bitable 公式表达式不能为空")
        field = await self._client.create_bitable_formula_field(
            app_token,
            table_id,
            field_name,
            formula_expression,
        )
        if field.type != BITABLE_FORMULA_FIELD_TYPE:
            raise FeishuAPIError("飞书创建公式字段成功，但响应中的字段类型不是公式")
        if not field.field_id:
            raise FeishuAPIError("飞书创建公式字段成功，但响应中缺少 field_id")
        if not field.field_name:
            raise FeishuAPIError("飞书创建公式字段成功，但响应中缺少 field_name")
        expression = (
            field.property.formula_expression
            if field.property and field.property.formula_expression
            else formula_expression
        )
        return BitableFormulaFieldResult(
            app_token=app_token,
            table_id=table_id,
            field_id=field.field_id,
            field_name=field.field_name,
            formula_expression=expression,
        )

    async def create_view(
        self,
        app_token: str,
        table_id: str,
        view_name: str,
        view_type: str,
    ) -> BitableViewResult:
        normalized_type = view_type.strip().lower()
        if normalized_type not in SUPPORTED_VIEW_TYPES:
            supported = "、".join(sorted(SUPPORTED_VIEW_TYPES))
            raise BitableValidationError(
                f"不支持的 Bitable 视图类型：{view_type}。可用类型：{supported}"
            )
        view = await self._client.create_bitable_view(
            app_token,
            table_id,
            view_name,
            normalized_type,
        )
        if not view.view_id:
            raise FeishuAPIError("飞书创建 Bitable 视图成功，但响应中缺少 view_id")
        if not view.view_name:
            raise FeishuAPIError("飞书创建 Bitable 视图成功，但响应中缺少 view_name")
        if not view.view_type:
            raise FeishuAPIError("飞书创建 Bitable 视图成功，但响应中缺少 view_type")
        return BitableViewResult(
            app_token=app_token,
            table_id=table_id,
            view_id=view.view_id,
            view_name=view.view_name,
            view_type=view.view_type,
        )

    async def list_dashboards(
        self,
        app_token: str,
        *,
        page_size: int,
        page_token: str | None = None,
    ) -> BitableDashboardsResult:
        dashboards, has_more, next_token, total = await self._client.list_bitable_dashboards(
            app_token,
            page_size=page_size,
            page_token=page_token,
        )
        result: list[BitableDashboardSchema] = []
        for dashboard in dashboards:
            if not dashboard.block_id:
                raise FeishuAPIError("飞书 Bitable 仪表盘响应缺少 block_id")
            if not dashboard.name:
                raise FeishuAPIError("飞书 Bitable 仪表盘响应缺少 name")
            result.append(
                BitableDashboardSchema(
                    block_id=dashboard.block_id,
                    name=dashboard.name,
                )
            )
        return BitableDashboardsResult(
            app_token=app_token,
            dashboards=result,
            has_more=has_more,
            page_token=next_token,
            total=total,
        )

    async def copy_dashboard(
        self,
        app_token: str,
        source_block_id: str,
        name: str,
    ) -> BitableDashboardCopyResult:
        block_id, copied_name = await self._client.copy_bitable_dashboard(
            app_token,
            source_block_id,
            name,
        )
        return BitableDashboardCopyResult(
            app_token=app_token,
            source_block_id=source_block_id,
            block_id=block_id,
            name=copied_name,
        )
