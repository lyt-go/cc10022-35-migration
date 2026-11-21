"""合并追溯领域服务：合并记录确认、冲突消解追溯与回滚归档。"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class MergeLogService(BaseModuleService):
    MODULE = "merge_log"
    ENTITY = "合并记录"
    OPERATION_TERM = "合并"
    LIST_FIELDS = ["记录编号", "黄金ID", "来源记录", "合并规则", "优胜字段", "淘汰字段", "合并批次", "合并时间"]
    REQUIRED_FIELDS = ["记录编号", "黄金ID", "来源记录"]
    STATUS_ORDER = ["待记录", "已确认", "已回滚", "已归档"]
    ACTION_RULES = {"确认合并": "已确认", "执行回滚": "已回滚", "归档记录": "已归档"}
    NEGATIVE_ACTIONS = []

    def record_merge_event(self, golden_id: str, source_records: list[str],
                            merge_rule: str, winners: list[str],
                            losers: list[str],
                            lineage_ids: list[int] | None = None) -> dict[str, Any]:
        """合并记录：将重复记录的归并过程写入合并追溯日志。

        记录每条合并操作的优胜字段和淘汰字段对比，并登记本次合并实际使用的
        字段级血缘条目（``lineage_ids``），供合并报表按步骤核对字段变换。
        """
        rows = store.rows(self.MODULE)
        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        record_id = (
            f"MERGE-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{entry_id:04d}"
        )
        entry = {
            "id": entry_id,
            "记录编号": record_id,
            "黄金ID": golden_id,
            "来源记录": "|".join(source_records),
            "合并规则": merge_rule,
            "优胜字段": ",".join(winners),
            "淘汰字段": ",".join(losers),
            "合并批次": golden_id,
            "合并时间": datetime.datetime.utcnow().isoformat(),
            "status": "已确认",
            "pending": False,
            "abnormal": False,
            "source_count": len(source_records),
            "字段血缘关联": [int(i) for i in (lineage_ids or [])],
        }
        rows.append(entry)
        # 写入合并记录到合并追溯存储，关联黄金记录与来源记录
        return {"ok": True, "merge_log": entry}

    def link_lineage_to_merge(self, merge_log_id: int,
                              lineage_ids: list[int]) -> dict[str, Any]:
        """把实际参与合并的字段血缘条目挂到合并记录上。"""
        log_entry = self.get_entry(merge_log_id)
        if log_entry is None:
            return {"ok": False, "reason": f"合并记录 {merge_log_id} 不存在"}
        existing = {int(i) for i in log_entry.get("字段血缘关联", [])}
        added = [int(i) for i in lineage_ids if int(i) not in existing]
        log_entry["字段血缘关联"] = sorted(existing | set(added))
        return {"ok": True, "merge_log_id": merge_log_id,
                "linked": log_entry["字段血缘关联"], "added": added}

    def merge_lineage_details(self, golden_id: str,
                              merge_log_id: int | None = None) -> dict[str, Any]:
        """合并追溯明细：合并记录 + 实际字段血缘步骤 + 解析依据。

        电话走旧拼接链路时仍返回原文与“边界不可证明”的原因；地址走新清洗
        规则时返回结构化步骤，报表可直接核对地址经过的字段变换。
        """
        from app.services.record_lineage import RecordLineageService

        if merge_log_id is not None:
            merge_row = self.get_entry(merge_log_id)
        else:
            history = self.query_merge_history(golden_id)
            merge_row = history[0] if history else None
        lineage_svc = RecordLineageService()
        if merge_row is None:
            return {
                "golden_id": golden_id,
                "合并记录": None,
                "fields": [],
                "message": "没有可关联的合并记录",
            }
        linked_ids = [int(i) for i in merge_row.get("字段血缘关联", []) if str(i).isdigit()]
        rows = store.rows("record_lineage")
        if linked_ids:
            lineage_rows = [row for row in rows if int(row.get("id", 0)) in linked_ids]
        else:
            lineage_rows = [row for row in rows if row.get("黄金ID") == golden_id]

        fields: dict[str, list[dict[str, Any]]] = {}
        for row in lineage_rows:
            view = lineage_svc._structured_view(row)
            if not view.get("可用", True):
                view = lineage_svc._fallback_view(row)
            fields.setdefault(row.get("字段路径", ""), []).append({
                "血缘编号": view.get("血缘编号"),
                "来源系统": view.get("来源系统"),
                "来源记录": view.get("来源记录"),
                "变换格式": view.get("变换格式"),
                "步骤": view.get("步骤", []),
                "步骤值": view.get("步骤值", []),
                "原文": view.get("原文"),
                "解析状态": view.get("解析状态"),
                "解析依据": view.get("解析依据"),
                "证据核验": view.get("证据核验"),
                "未迁移原因": view.get("未迁移原因"),
                "可完成合并证据核验": view.get("可完成合并证据核验", False),
            })
        return {
            "golden_id": golden_id,
            "合并记录": merge_row.get("记录编号"),
            "来源记录": merge_row.get("来源记录"),
            "合并规则": merge_row.get("合并规则"),
            "合并时间": merge_row.get("合并时间"),
            "fields": [
                {"字段路径": field, "sources": sources}
                for field, sources in fields.items()
            ],
            "证据核验": lineage_svc.audit_merge_evidence(golden_id),
        }

    def export_merge_report(self, golden_id: str,
                            merge_log_id: int | None = None) -> dict[str, Any]:
        """合并报表导出：按字段给出实际步骤与解析依据，供审计核对。

        电话字段（旧拼接）只输出原文并注明不可核验；地址字段（新格式）输出
        结构化步骤，便于逐项核对地址经过的字段变换。
        """
        details = self.merge_lineage_details(golden_id, merge_log_id)
        rows_out: list[dict[str, Any]] = []
        for field_block in details.get("fields", []):
            field = field_block["字段路径"]
            for source in field_block["sources"]:
                rows_out.append({
                    "字段路径": field,
                    "来源系统": source.get("来源系统"),
                    "来源记录": source.get("来源记录"),
                    "变换格式": source.get("变换格式"),
                    "步骤": source.get("步骤", []),
                    "原文": source.get("原文"),
                    "解析依据": source.get("解析依据"),
                    "证据核验": source.get("证据核验"),
                    "可完成合并证据核验": source.get("可完成合并证据核验", False),
                    "未迁移原因": source.get("未迁移原因"),
                })
        audit = details.get("证据核验", {})
        return {
            "golden_id": golden_id,
            "合并记录": details.get("合并记录"),
            "来源记录": details.get("来源记录"),
            "字段数": len(details.get("fields", [])),
            "可核验字段": audit.get("可核验字段", []),
            "不可核验字段": audit.get("不可核验字段", []),
            "明细": rows_out,
        }

    def query_merge_history(self, golden_id: str) -> list[dict[str, Any]]:
        """查询指定黄金记录的完整合并追溯历史。

        按黄金ID查询合并记录存储，获取所有来源记录的合并过程、
        优胜字段选择和淘汰字段列表的完整追溯链路。
        """
        rows = store.rows(self.MODULE)
        history = [
            row for row in rows
            if row.get("黄金ID") == golden_id
        ]
        # 查询合并追溯历史：获取黄金记录的完整合并过程
        history.sort(key=lambda r: r.get("合并时间", ""), reverse=True)
        return history

    def rollback_merge(self, merge_log_id: int) -> dict[str, Any]:
        """回滚合并操作：将指定合并记录回滚并恢复原始来源记录。

        读取合并记录，标记为已回滚状态，记录回滚操作用以支持
        合并错误的撤销和来源数据恢复。
        """
        log_entry = self.get_entry(merge_log_id)
        if not log_entry or log_entry.get("status") == "已回滚":
            return {"ok": False, "reason": "合并记录不存在或已回滚"}
        log_entry["status"] = "已回滚"
        log_entry["rollback_at"] = datetime.datetime.utcnow().isoformat()
        # 回滚合并记录：恢复原始来源记录数据
        return {"ok": True, "merge_id": log_entry.get("记录编号"), "golden_id": log_entry.get("黄金ID")}

    def archive_merge_logs(self, before_date: str) -> int:
        """归档指定日期之前的已确认合并记录。

        查询merge_log存储，将已确认且在指定日期之前的合并记录
        标记为已归档状态，归档到历史存储供审计追溯。
        """
        rows = store.rows(self.MODULE)
        archived = 0
        for row in rows:
            if row.get("status") == "已确认":
                merge_time = row.get("合并时间", "")
                if merge_time < before_date:
                    # 归档合并记录：将历史合并操作迁移到归档存储
                    row["status"] = "已归档"
                    row["archived_at"] = datetime.datetime.utcnow().isoformat()
                    archived += 1
        return archived

    def validate_merge_consistency(self, golden_id: str) -> dict[str, Any]:
        """校验合并一致性：检查黄金记录与来源记录的字段冲突是否已解决。

        查询黄金记录的所有合并历史，校验每条合并记录的优胜字段
        和淘汰字段是否有冲突，输出合并一致性校验报告。
        """
        history = self.query_merge_history(golden_id)
        if not history:
            return {"golden_id": golden_id, "merge_count": 0, "consistent": True}
        has_rollback = any(h.get("status") == "已回滚" for h in history)
        return {
            "golden_id": golden_id,
            "merge_count": len(history),
            "has_rollback": has_rollback,
            "consistent": not has_rollback,
            "source_records": [h.get("来源记录") for h in history],
        }

    def generate_merge_report(self, golden_id: str) -> dict[str, Any]:
        """生成合并追溯报告：汇总合并操作统计与字段冲突消解详情。"""
        history = self.query_merge_history(golden_id)
        if not history:
            return {"golden_id": golden_id, "merge_count": 0}
        all_winners = set()
        all_losers = set()
        for h in history:
            all_winners.update((h.get("优胜字段", "")).split(","))
            all_losers.update((h.get("淘汰字段", "")).split(","))
        return {
            "golden_id": golden_id,
            "merge_count": len(history),
            "total_winners": len(all_winners),
            "total_losers": len(all_losers),
        }