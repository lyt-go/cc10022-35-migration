"""血缘与合并的领域接口：迁移、双格式查询、切换演练与合并证据核验。

这些路径必须在通用资源路由之前注册：``/api/{module}/{entry_id}`` 的
``entry_id`` 是整数，静态子路径如果排在它后面会被抢先匹配。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.lineage_switch import lineage_switch
from app.services.merge_log import MergeLogService
from app.services.record_lineage import RecordLineageService

router = APIRouter(prefix="/api", tags=["血缘与合并"])

lineage_service = RecordLineageService()
merge_service = MergeLogService()


class MigrationPayload(BaseModel):
    golden_id: str | None = None


class SwitchFailurePayload(BaseModel):
    scope: str = Field(default="both", description="write / read / both")
    reason: str = "部署演练：模拟结构化血缘切换失败"


@router.post("/record_lineage/legacy-migration")
def migrate_legacy_lineage(payload: MigrationPayload | None = None) -> dict[str, Any]:
    """把旧竖线拼接的字段血缘迁移为结构化步骤（幂等）。"""
    golden_id = payload.golden_id if payload else None
    return lineage_service.migrate_legacy_lineage(golden_id)


@router.get("/record_lineage/field-lineage")
def query_field_lineage(
    golden_id: str = Query(...),
    format: str = Query(default="auto", pattern="^(auto|legacy|structured)$"),
) -> dict[str, Any]:
    """按指定格式查询字段血缘；legacy 不受切换开关影响。"""
    items = lineage_service.query_field_lineage(golden_id, output_format=format)
    return {
        "golden_id": golden_id,
        "format": format,
        "count": len(items),
        "items": items,
        "switch": lineage_switch.status(),
    }


@router.get("/record_lineage/merge-evidence/{golden_id}")
def audit_merge_evidence(golden_id: str) -> dict[str, Any]:
    """审计员视图：按字段判断能否完成合并证据核验。"""
    return lineage_service.audit_merge_evidence(golden_id)


@router.get("/record_lineage/dual-format-check")
def dual_format_check(golden_id: str | None = Query(default=None)) -> dict[str, Any]:
    """部署前核对：旧链、含竖线的新步骤、切换失败回退与两种查询。"""
    return lineage_service.run_dual_format_check(golden_id)


@router.get("/lineage-switch")
def switch_status() -> dict[str, Any]:
    return lineage_switch.status()


@router.get("/lineage-switch/history")
def switch_history() -> dict[str, Any]:
    return lineage_service.switch_history()


@router.post("/lineage-switch/simulate-failure")
def simulate_failure(payload: SwitchFailurePayload) -> dict[str, Any]:
    """演练切换失败：仅改变结构化链路，原字段血缘查询保持可用。"""
    return lineage_switch.simulate_failure(scope=payload.scope, reason=payload.reason)


@router.post("/lineage-switch/recover")
def recover_switch() -> dict[str, Any]:
    return lineage_switch.recover()


@router.get("/merge_log/report/{golden_id}")
def export_merge_report(golden_id: str,
                        merge_log_id: int | None = Query(default=None)) -> dict[str, Any]:
    """合并报表：按字段输出实际步骤、原文与解析依据。"""
    return merge_service.export_merge_report(golden_id, merge_log_id)


@router.get("/merge_log/{merge_log_id}/lineage-details")
def merge_lineage_details(merge_log_id: int) -> dict[str, Any]:
    """合并追溯明细：合并记录关联的实际血缘步骤及解析依据。"""
    entry = merge_service.get_entry(merge_log_id)
    if entry is None:
        return {"ok": False, "reason": f"合并记录 {merge_log_id} 不存在"}
    return merge_service.merge_lineage_details(entry.get("黄金ID", ""), merge_log_id)
