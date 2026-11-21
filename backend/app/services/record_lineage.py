"""记录级血缘领域服务：结构化字段血缘、旧格式迁移、合并证据核验与切换回退。

存储约定
--------
每条血缘记录的权威步骤写在 ``变换步骤`` 里：一个按 ``顺序`` 排列的列表，
每步的 ``值`` 是写入时的原样表达式。``变换记录`` 仅作为展示/兼容字段：

* 新链路写入：``变换格式 = 结构化``，表达式逐条原样保存，绝不按竖线切分；
* 旧链路迁移：``变换格式 = 旧竖线拼接``，保留 ``原文``；能证明边界时拆成步骤，
  不能证明时 ``变换步骤`` 留空并给出 ``未迁移原因``，绝不猜测；
* 切换失败：结构化不可用时，原文视图始终可查询，结构化视图显式标记回退。
"""
from __future__ import annotations

import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.services.lineage_switch import lineage_switch
from app.services.lineage_transform import (
    LEGACY_FORMAT,
    PARSE_STRUCTURED,
    PARSE_UNPROVEN,
    STRUCTURED_FORMAT,
    display_text,
    make_step,
    normalize_steps,
    now_iso,
    parse_legacy_transform,
    step_english_view,
    structured_transform_metadata,
)
from app.store import store

_UNPROVEN_KEY = "未迁移原因"


class RecordLineageService(BaseModuleService):
    MODULE = "record_lineage"
    ENTITY = "血缘记录"
    OPERATION_TERM = "校验"
    # 通用列表/登记/导出仍按原有 8 个字段工作；结构化元数据作为附加键随行返回，
    # 避免把“变换格式/解析依据”当成人工登记字段。
    LIST_FIELDS = ["血缘编号", "黄金ID", "来源记录", "来源系统", "字段路径", "变换记录", "生效时间", "失效时间"]
    REQUIRED_FIELDS = ["血缘编号", "黄金ID", "来源记录"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用记录": "已停用"}
    NEGATIVE_ACTIONS = ["停用记录"]

    # ── 登记入口：表单写入也走结构化链路 ─────────────────────────────────
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """通用登记入口：``变换记录`` 视为一条表达式原样保存。

        旧格式迁移走 ``migrate_legacy_lineage``；这里不做竖线切分，避免把
        “新写入”误当成旧拼接数据。
        """
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        steps_input = values.get("变换步骤")
        if isinstance(steps_input, list):
            transformations: list[Any] | str = steps_input
        else:
            transformations = values.get("变换记录") or ""
        result = self.record_field_lineage(
            str(values.get("黄金ID", "")),
            str(values.get("来源记录", "")),
            str(values.get("来源系统", "")),
            str(values.get("字段路径", "")),
            transformations,
        )
        entry = result["lineage"]
        entry.update({
            "血缘编号": values.get("血缘编号") or entry.get("血缘编号"),
            "生效时间": values.get("生效时间") or entry.get("生效时间"),
            "失效时间": values.get("失效时间") or "",
            # 与其他模块一致：人工登记先落在草稿态，动作流转让它生效
            "status": self.STATUS_ORDER[0],
            "pending": True,
        })
        return entry, []

    # ── 写入 ──────────────────────────────────────────────────────────────
    def record_field_lineage(self, golden_id: str, source_record_id: str,
                               source_system: str, field_path: str,
                               transformations: list[Any] | str | None,
                               *,
                               source_rule: str | None = None,
                               parse_basis: str | None = None,
                               legacy: bool = False) -> dict[str, Any]:
        """记录字段级血缘：结构化保存每一步的值与顺序。

        ``transformations`` 为列表时按给定顺序逐条原样保存；为字符串时视为
        **一条**表达式（即使含竖线也不拆分），保证新写入表达式原样保留。
        仅当显式 ``legacy=True`` 时才按旧竖线格式解析。
        """
        rows = store.rows(self.MODULE)
        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        lineage_id = (
            f"LINE-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{entry_id:04d}"
        )
        effective_time = now_iso()

        entry: dict[str, Any] = {
            "id": entry_id,
            "血缘编号": lineage_id,
            "黄金ID": golden_id,
            "来源记录": source_record_id,
            "来源系统": source_system,
            "字段路径": field_path,
            "生效时间": effective_time,
            "失效时间": "",
            "status": "已生效",
            "pending": False,
            "abnormal": False,
        }

        switch = lineage_switch.status()
        if not lineage_switch.structured_write_enabled:
            # 结构化写入不可用：退化为原文存储，保证原字段血缘仍可查询
            if isinstance(transformations, str):
                raw = transformations
                raw_values = [transformations]
            else:
                raw_values = [str(step.get("值") if isinstance(step, dict) else step)
                              for step in (transformations or [])]
                raw = "|".join(raw_values)
            entry.update({
                "变换记录": raw,
                "原文": raw,
                "原始表达式": raw_values,
                "变换格式": "切换回退（原文）",
                "解析状态": "结构化写入不可用（已回退原文）",
                "解析依据": (
                    f"{lineage_switch.failure_reason or '结构化链路切换失败'}；"
                    "已保留原文，旧字段血缘查询不受影响"
                ),
                "证据核验": "不可核验",
                "核验说明": "结构化写入未完成，只能按原文查询，待链路恢复后重试迁移",
                "清洗规则": source_rule or "",
                "迁移时间": now_iso(),
                "transform_count": len(raw_values),
                "structured_available": False,
            })
            rows.append(entry)
            return {
                "ok": True,
                "degraded": True,
                "switch": switch,
                "lineage": self._legacy_view(entry),
                "message": "结构化血缘切换失败，已回退原文；原字段血缘仍可查询",
            }

        if legacy:
            parsed = parse_legacy_transform(transformations)
            # 原文原样保留，绝不重新拼接/改写
            entry.update({
                "变换记录": "" if transformations is None else str(transformations),
                "原文": "" if transformations is None else str(transformations),
                "变换格式": LEGACY_FORMAT,
                "变换步骤": parsed["步骤"],
                "解析状态": parsed["解析状态"],
                "解析依据": parsed["解析依据"],
                "证据核验": parsed["证据核验"],
                "核验说明": parsed["核验说明"],
                "迁移时间": now_iso(),
                "transform_count": len(parsed["步骤"]),
                "structured_available": True,
            })
            if parsed["解析状态"] == PARSE_UNPROVEN:
                entry[_UNPROVEN_KEY] = parsed["解析依据"]
        else:
            steps = normalize_steps(transformations)
            metadata = structured_transform_metadata(
                steps, parse_basis=parse_basis, source_rule=source_rule)
            entry.update({
                "变换记录": display_text(steps),
                "原文": display_text(steps),
                "原始表达式": [step.get("值") for step in steps],
                "变换格式": STRUCTURED_FORMAT,
                "变换步骤": steps,
                **metadata,
                "transform_count": len(steps),
                "structured_available": True,
            })
        rows.append(entry)
        # 关联血缘记录：结构化步骤即为黄金字段到原始来源的完整追溯链
        return {
            "ok": True,
            "degraded": False,
            "switch": switch,
            "lineage": self._structured_view(entry),
        }

    # ── 旧格式迁移 ────────────────────────────────────────────────────────
    def migrate_legacy_lineage(self, golden_id: str | None = None) -> dict[str, Any]:
        """把旧竖线拼接记录迁移为结构化字段血缘（幂等）。

        能证明边界：写入 ``变换步骤`` 并标记推定/已证明；
        不能证明：保留 ``原文``、``变换步骤`` 留空、写入 ``未迁移原因``。
        迁移不修改 ``变换记录``，原文始终可用于回退查询。
        """
        rows = store.rows(self.MODULE)
        targets = [r for r in rows if golden_id is None or r.get("黄金ID") == golden_id]
        summary: dict[str, Any] = {
            "golden_id": golden_id,
            "scanned": len(targets),
            "already_structured": 0,
            "migrated": 0,
            "unproven": 0,
            "skipped": 0,
            "items": [],
        }
        for row in targets:
            if row.get("变换格式") == STRUCTURED_FORMAT and "变换步骤" in row:
                summary["already_structured"] += 1
                continue
            if "变换记录" not in row and "原文" not in row:
                summary["skipped"] += 1
                continue
            if row.get("变换格式") == "切换回退（原文）" and "原始表达式" in row:
                # 结构化恢复后，把回退时保留的原始表达式补回结构化
                raw_values = row["原始表达式"]
                steps = (
                    normalize_steps(raw_values)
                    if isinstance(raw_values, list)
                    else [make_step(1, raw_values)]
                )
                metadata = structured_transform_metadata(
                    steps, source_rule=row.get("清洗规则") or None)
                row.update({
                    "变换步骤": steps,
                    "变换格式": STRUCTURED_FORMAT,
                    "变换记录": display_text(steps),
                    "原文": display_text(steps),
                    **_rename_parse_meta(metadata),
                    "transform_count": len(steps),
                    "structured_available": True,
                    "迁移时间": now_iso(),
                })
                summary["migrated"] += 1
                summary["items"].append(self._migration_item(row, "已从切换回退原文恢复结构化"))
                continue

            raw = row.get("原文", row.get("变换记录", ""))
            # 显式标记为结构化却缺少步骤的记录：表达式只有一条，原文即唯一步骤
            if row.get("变换格式") == STRUCTURED_FORMAT:
                steps = [make_step(1, raw)] if raw != "" else []
                metadata = structured_transform_metadata(
                    steps, source_rule=row.get("清洗规则") or None)
                row.update({
                    "变换步骤": steps,
                    **_rename_parse_meta(metadata),
                    "transform_count": len(steps),
                    "structured_available": True,
                    "迁移时间": now_iso(),
                })
                summary["migrated"] += 1
                summary["items"].append(
                    self._migration_item(row, "结构化记录缺少步骤列表，按单条表达式补齐"))
                continue

            parsed = parse_legacy_transform(raw)
            row.update({
                "变换格式": row.get("变换格式") or LEGACY_FORMAT,
                "原文": raw,
                "变换步骤": parsed["步骤"],
                "解析状态": parsed["解析状态"],
                "解析依据": parsed["解析依据"],
                "证据核验": parsed["证据核验"],
                "核验说明": parsed["核验说明"],
                "迁移时间": now_iso(),
                "structured_available": True,
            })
            row["transform_count"] = len(parsed["步骤"])
            if parsed["解析状态"] == PARSE_UNPROVEN:
                row[_UNPROVEN_KEY] = parsed["解析依据"]
                row["abnormal"] = True
                summary["unproven"] += 1
            else:
                row.pop(_UNPROVEN_KEY, None)
                summary["migrated"] += 1
            summary["items"].append(self._migration_item(row, parsed["解析依据"]))

        summary["switch"] = lineage_switch.status()
        summary["message"] = (
            f"迁移完成：{summary['migrated']} 条已结构化，"
            f"{summary['unproven']} 条边界不可证明已保留原文"
        )
        return summary

    def _migration_item(self, row: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "血缘编号": row.get("血缘编号"),
            "黄金ID": row.get("黄金ID"),
            "字段路径": row.get("字段路径"),
            "变换格式": row.get("变换格式"),
            "解析状态": row.get("解析状态"),
            "证据核验": row.get("证据核验"),
            "原文": row.get("原文", row.get("变换记录")),
            "步骤": row.get("变换步骤", []),
            "说明": reason,
        }

    # ── 读取：原文 / 结构化 / 自动回退 ──────────────────────────────────
    def query_field_lineage(self, golden_id: str,
                             output_format: str = "auto") -> list[dict[str, Any]]:
        """查询指定黄金记录的字段级血缘。

        ``output_format``：
        - ``legacy``：只返回旧字段血缘原文，永远可用，不受切换开关影响；
        - ``structured``：返回结构化步骤；读取不可用时返回显式回退对象；
        - ``auto``：结构化可用则结构化，否则自动回退原文。
        """
        rows = store.rows(self.MODULE)
        lineage = [
            row for row in rows
            if row.get("黄金ID") == golden_id and row.get("status") == "已生效"
        ]
        lineage.sort(key=lambda r: (r.get("生效时间", ""), int(r.get("id", 0))))
        fmt = (output_format or "auto").lower()
        if fmt == "legacy":
            return [self._legacy_view(row) for row in lineage]
        if fmt == "structured":
            return [self._structured_view(row) for row in lineage]
        if lineage_switch.structured_read_enabled:
            return [self._structured_view(row) for row in lineage]
        return [self._fallback_view(row) for row in lineage]

    def query_legacy_field_lineage(self, golden_id: str) -> list[dict[str, Any]]:
        """查询原文视图：旧字段血缘不依赖结构化链路，始终可读。"""
        return self.query_field_lineage(golden_id, output_format="legacy")

    def query_structured_field_lineage(self, golden_id: str) -> list[dict[str, Any]]:
        """查询结构化视图；切换失败时返回带原因的回退对象而不是报错。"""
        return self.query_field_lineage(golden_id, output_format="structured")

    def _legacy_view(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("原文", row.get("变换记录", ""))
        return {
            "血缘编号": row.get("血缘编号"),
            "黄金ID": row.get("黄金ID"),
            "来源记录": row.get("来源记录"),
            "来源系统": row.get("来源系统"),
            "字段路径": row.get("字段路径"),
            "变换记录": row.get("变换记录", ""),
            "原文": raw,
            "变换格式": row.get("变换格式", LEGACY_FORMAT),
            "输出格式": "原文",
            "可回读": True,
            "说明": "旧字段血缘原文，切换失败时仍可直接查询",
            "证据核验": row.get("证据核验", "不可核验"),
            "解析状态": row.get("解析状态", ""),
            "解析依据": row.get("解析依据", ""),
        }

    def _structured_view(self, row: dict[str, Any]) -> dict[str, Any]:
        if not lineage_switch.structured_read_enabled:
            return self._fallback_view(row)
        if "变换步骤" in row:
            steps = row.get("变换步骤", [])
            meta = row
        else:
            # 尚未迁移的旧记录按需解析；不可证明时仍保留原文
            parsed = parse_legacy_transform(row.get("原文", row.get("变换记录", "")))
            steps = parsed["步骤"]
            meta = {**row, **parsed}
            if parsed["解析状态"] == PARSE_UNPROVEN:
                meta[_UNPROVEN_KEY] = parsed["解析依据"]
        unproven = meta.get("解析状态") == PARSE_UNPROVEN or not steps
        view: dict[str, Any] = {
            "血缘编号": row.get("血缘编号"),
            "黄金ID": row.get("黄金ID"),
            "来源记录": row.get("来源记录"),
            "来源系统": row.get("来源系统"),
            "字段路径": row.get("字段路径"),
            "变换格式": row.get("变换格式") or LEGACY_FORMAT,
            "输出格式": "结构化",
            "可用": True,
            "原文": row.get("原文", row.get("变换记录", "")),
            "变换记录": row.get("变换记录", ""),
            "步骤": steps,
            "步骤值": [step.get("值") for step in steps],
            "步骤顺序": [step.get("顺序") for step in steps],
            "步骤数": len(steps),
            "解析状态": meta.get("解析状态", PARSE_STRUCTURED),
            "解析依据": meta.get("解析依据", ""),
            "证据核验": meta.get("证据核验", "不可核验"),
            "核验说明": meta.get("核验说明", ""),
            "清洗规则": meta.get("清洗规则", ""),
            "迁移时间": meta.get("迁移时间", ""),
            "可完成合并证据核验": bool(steps) and meta.get("证据核验") == "可核验",
            "程序视图": step_english_view(steps),
        }
        if unproven:
            view["未迁移原因"] = (
                meta.get(_UNPROVEN_KEY)
                or meta.get("解析依据")
                or "旧格式无法证明步骤边界，未生成结构化步骤"
            )
            view["说明"] = "保留原文，未拆分步骤"
        return view

    def _fallback_view(self, row: dict[str, Any]) -> dict[str, Any]:
        reason = (
            lineage_switch.failure_reason
            or "结构化血缘读取链路不可用"
        )
        return {
            "血缘编号": row.get("血缘编号"),
            "黄金ID": row.get("黄金ID"),
            "来源记录": row.get("来源记录"),
            "来源系统": row.get("来源系统"),
            "字段路径": row.get("字段路径"),
            "变换格式": "原文回退",
            "输出格式": "原文回退",
            "可用": False,
            "原文": row.get("原文", row.get("变换记录", "")),
            "变换记录": row.get("变换记录", ""),
            "步骤": [],
            "步骤数": 0,
            "解析状态": "结构化读取不可用（返回原文）",
            "解析依据": f"{reason}；已自动回退原文，旧字段血缘查询不受影响",
            "证据核验": "不可核验",
            "核验说明": "结构化链路不可用，暂不能按步骤核验合并证据",
            "回退": True,
            "可完成合并证据核验": False,
        }

    # ── 合并证据核验 ─────────────────────────────────────────────────────
    def _lineage_rows_for_merge(self, golden_id: str, merge_row: dict[str, Any] | None = None
                                 ) -> list[dict[str, Any]]:
        rows = store.rows(self.MODULE)
        if merge_row is not None:
            linked = [int(i) for i in merge_row.get("字段血缘关联", []) if str(i).isdigit()]
            if linked:
                return [row for row in rows if int(row.get("id", 0)) in linked]
        return [row for row in rows if row.get("黄金ID") == golden_id]

    def audit_merge_evidence(self, golden_id: str) -> dict[str, Any]:
        """审计员视图：逐个字段判断能否完成合并证据核验。

        对每个字段列出实际步骤、解析依据、证据状态；只有步骤完整且证据被
        证实的字段才标记 ``可核验``。旧竖线格式即使能推定拆分，也注明
        “顺序可读但边界未证明”，因此不能作为合并证据。
        """
        merge_rows = [
            row for row in store.rows("merge_log")
            if row.get("黄金ID") == golden_id and row.get("status") != "已回滚"
        ]
        merge_row = merge_rows[-1] if merge_rows else None
        lineage_rows = self._lineage_rows_for_merge(golden_id, merge_row)

        fields: dict[str, list[dict[str, Any]]] = {}
        for row in lineage_rows:
            view = self._structured_view(row)
            if not view.get("可用", True):
                view = self._fallback_view(row)
            field = row.get("字段路径", "")
            fields.setdefault(field, []).append(view)

        field_reports: list[dict[str, Any]] = []
        verifiable_fields: list[str] = []
        blocked_fields: list[str] = []
        for field, views in fields.items():
            field_verifiable = all(v.get("可完成合并证据核验") for v in views)
            if field_verifiable:
                verifiable_fields.append(field)
            else:
                blocked_fields.append(field)
            reasons: list[str] = []
            for view in views:
                if view.get("可用", True) is False:
                    reasons.append("结构化链路不可用，已回退原文")
                elif not view.get("步骤"):
                    reasons.append(view.get("未迁移原因") or "无结构化步骤")
                elif view.get("证据核验") != "可核验":
                    reasons.append(view.get("核验说明") or "步骤边界未被证明")
            field_reports.append({
                "字段路径": field,
                "可完成合并证据核验": field_verifiable,
                "结论": "可核验" if field_verifiable else "不可核验",
                "原因": "；".join(dict.fromkeys(reasons)),
                "来源记录": [v.get("来源记录") for v in views],
                "条目": [{
                    "血缘编号": v.get("血缘编号"),
                    "来源记录": v.get("来源记录"),
                    "来源系统": v.get("来源系统"),
                    "变换格式": v.get("变换格式"),
                    "解析状态": v.get("解析状态"),
                    "解析依据": v.get("解析依据"),
                    "证据核验": v.get("证据核验"),
                    "步骤": v.get("步骤", []),
                    "原文": v.get("原文"),
                    "可完成合并证据核验": v.get("可完成合并证据核验", False),
                } for v in views],
            })

        return {
            "golden_id": golden_id,
            "合并记录": merge_row.get("记录编号") if merge_row else None,
            "来源记录": merge_row.get("来源记录") if merge_row else None,
            "fields": field_reports,
            "可核验字段": verifiable_fields,
            "不可核验字段": blocked_fields,
            "summary": {
                "total_fields": len(field_reports),
                "verifiable": len(verifiable_fields),
                "blocked": len(blocked_fields),
                "conclusion": (
                    "全部字段可完成合并证据核验"
                    if field_reports and not blocked_fields
                    else "存在无法完成合并证据核验的字段，需补充迁移证据"
                ),
            },
            "switch": lineage_switch.status(),
        }

    # ── 既有图谱/导出能力（改为消费结构化步骤） ──────────────────────────
    def build_lineage_graph(self, golden_id: str) -> dict[str, Any]:
        """构建血缘图谱：节点与边都使用结构化步骤及其顺序。"""
        lineages = self.query_field_lineage(golden_id)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        visited = set()
        for lineage in lineages:
            source = lineage.get("来源记录", "")
            field = lineage.get("字段路径", "")
            if source and source not in visited:
                visited.add(source)
                nodes.append({"id": source, "type": "source_record",
                              "system": lineage.get("来源系统")})
            field_node_id = f"{golden_id}:{field}"
            if field_node_id not in visited:
                visited.add(field_node_id)
                nodes.append({"id": field_node_id, "type": "golden_field", "field": field})
            steps = lineage.get("步骤", [])
            edges.append({
                "from": source,
                "to": field_node_id,
                "transformations": [step.get("值") for step in steps],
                "steps": steps,
                "parse_basis": lineage.get("解析依据", ""),
                "evidence": lineage.get("证据核验", "不可核验"),
            })
        # 构建血缘图谱：关联来源记录和字段路径生成DAG关系图
        return {"golden_id": golden_id, "nodes": nodes, "edges": edges}

    def validate_lineage_completeness(self, golden_id: str,
                                       expected_sources: list[str]) -> dict[str, Any]:
        """校验血缘完整性：确认黄金记录的每条来源都有字段级血缘关联。"""
        lineages = [
            row for row in store.rows(self.MODULE)
            if row.get("黄金ID") == golden_id and row.get("status") == "已生效"
        ]
        covered = set()
        for lineage in lineages:
            covered.add(lineage.get("来源记录", ""))
        missing = [s for s in expected_sources if s not in covered]
        return {
            "golden_id": golden_id,
            "expected_sources": len(expected_sources),
            "lineage_entries": len(lineages),
            "covered_sources": len(covered),
            "missing_sources": missing,
            "completeness": round(len(covered) / max(len(expected_sources), 1) * 100, 2),
        }

    def expire_lineage_entries(self, golden_id: str, expire_reason: str) -> int:
        """失效血缘记录：当黄金记录更新时标记旧血缘为失效状态。"""
        rows = store.rows(self.MODULE)
        expired = 0
        for row in rows:
            if row.get("黄金ID") == golden_id and row.get("status") == "已生效":
                row["status"] = "已停用"
                row["失效时间"] = now_iso()
                row["expire_reason"] = expire_reason
                expired += 1
        return expired

    def export_lineage_trace(self, golden_id: str) -> dict[str, Any]:
        """导出血缘追溯：按结构化步骤输出字段级完整来源链路。"""
        lineages = self.query_field_lineage(golden_id)
        trace: dict[str, list[dict[str, Any]]] = {}
        for lineage in lineages:
            field = lineage.get("字段路径", "")
            trace.setdefault(field, []).append({
                "source_system": lineage.get("来源系统"),
                "source_record": lineage.get("来源记录"),
                "transformation_format": lineage.get("变换格式"),
                "steps": lineage.get("步骤", []),
                "transformations": [step.get("值") for step in lineage.get("步骤", [])],
                "parse_basis": lineage.get("解析依据", ""),
                "evidence_verifiable": lineage.get("可完成合并证据核验", False),
                "effective_time": lineage.get("生效时间") or lineage.get("迁移时间"),
            })
        # 导出血缘追溯：构建字段级完整来源追溯链路
        return {"golden_id": golden_id, "field_trace": trace,
                "total_entries": len(lineages), "switch": lineage_switch.status()}

    def query_lineage_by_system(self, source_system: str) -> list[dict[str, Any]]:
        """查询给定来源系统影响的所有黄金记录，反向追溯血缘。"""
        rows = store.rows(self.MODULE)
        return [
            row for row in rows
            if row.get("来源系统") == source_system and row.get("status") == "已生效"
        ]

    # ── 切换开关 ─────────────────────────────────────────────────────────
    def switch_status(self) -> dict[str, Any]:
        return lineage_switch.status()

    def simulate_switch_failure(self, scope: str = "both",
                                 reason: str = "部署演练：模拟结构化血缘切换失败") -> dict[str, Any]:
        return lineage_switch.simulate_failure(scope=scope, reason=reason)

    def recover_switch(self) -> dict[str, Any]:
        return lineage_switch.recover()

    def switch_history(self) -> dict[str, Any]:
        return {"status": lineage_switch.status(), "history": lineage_switch.history}

    # ── 部署前双格式核对 ─────────────────────────────────────────────────
    def run_dual_format_check(self, golden_id: str | None = None) -> dict[str, Any]:
        """正式部署前核对：旧链、含竖线的新步骤、切换失败回退与两种查询。

        检查结束后恢复切换开关原状态；最后分别查询原文和新格式数据。
        """
        target = golden_id or self._default_dual_format_golden()
        rows = [
            row for row in store.rows(self.MODULE)
            if row.get("黄金ID") == target
        ]
        legacy_rows = [r for r in rows if (r.get("变换格式") or LEGACY_FORMAT) == LEGACY_FORMAT]
        structured_rows = [r for r in rows if r.get("变换格式") == STRUCTURED_FORMAT]

        checks: list[dict[str, Any]] = []

        # 1) 旧链核对：原文与迁移后的步骤一致（或明确不可证明）
        if legacy_rows:
            legacy_row = legacy_rows[0]
            parsed = parse_legacy_transform(
                legacy_row.get("原文", legacy_row.get("变换记录", "")))
            stored_steps = legacy_row.get("变换步骤")
            if stored_steps is None:
                steps = parsed["步骤"]
                status = parsed["解析状态"]
            else:
                steps = stored_steps
                status = legacy_row.get("解析状态", parsed["解析状态"])
            checks.append({
                "name": "旧链回读",
                "ok": True,
                "detail": (
                    f"{legacy_row.get('血缘编号')} 原文={legacy_row.get('原文', legacy_row.get('变换记录'))!r}，"
                    f"解析状态={status}，步骤={[s.get('值') for s in steps]}"
                ),
                "血缘编号": legacy_row.get("血缘编号"),
                "原文": legacy_row.get("原文", legacy_row.get("变换记录")),
                "steps": steps,
                "解析状态": status,
                "证据核验": legacy_row.get("证据核验", parsed["证据核验"]),
            })
        else:
            checks.append({"name": "旧链回读", "ok": False,
                           "detail": f"黄金记录 {target} 没有旧竖线格式血缘可核对"})

        # 2) 含竖线的新步骤核对：必须逐字保留，且不被拆成多步
        pipe_row = next(
            (r for r in structured_rows
             if any("|" in str(step.get("值", "")) for step in r.get("变换步骤", []))),
            None,
        )
        if pipe_row:
            pipe_steps = [s for s in pipe_row.get("变换步骤", []) if "|" in str(s.get("值", ""))]
            base_steps = pipe_row.get("原始表达式")
            if isinstance(base_steps, list) and base_steps:
                # 与写入时的原始表达式逐条比对：数量和值都必须一致，证明竖线未被当作分隔符
                exact = (
                    len(pipe_row.get("变换步骤", [])) == len(base_steps)
                    and all(
                        step.get("值") == base
                        for step, base in zip(pipe_row.get("变换步骤", []), base_steps)
                    )
                )
            else:
                exact = bool(pipe_steps)
            expected = pipe_steps[0]["值"] if pipe_steps else ""
            checks.append({
                "name": "含竖线新步骤原样保留",
                "ok": bool(pipe_steps) and exact,
                "detail": (
                    f"{pipe_row.get('血缘编号')} 包含 {len(pipe_steps)} 个带竖线的步骤，"
                    f"步骤总数={len(pipe_row.get('变换步骤', []))}，表达式逐字保留={exact}"
                ),
                "血缘编号": pipe_row.get("血缘编号"),
                "步骤": pipe_row.get("变换步骤", []),
                "含竖线步骤值": expected,
                "解析依据": pipe_row.get("解析依据", ""),
                "证据核验": pipe_row.get("证据核验", ""),
            })
        else:
            checks.append({"name": "含竖线新步骤原样保留", "ok": False,
                           "detail": f"黄金记录 {target} 没有含竖线的新步骤可核对"})

        # 3) 模拟切换失败，核对原文与新格式查询
        previous = {
            "write": lineage_switch.structured_write_enabled,
            "read": lineage_switch.structured_read_enabled,
            "scope": lineage_switch.failure_scope,
            "reason": lineage_switch.failure_reason,
        }
        lineage_switch.simulate_failure(scope="both", reason="部署前演练：模拟切换失败")
        try:
            legacy_query = self.query_field_lineage(target, output_format="legacy")
            structured_query = self.query_field_lineage(target, output_format="structured")
            legacy_ok = bool(legacy_query) and all(
                item.get("原文") is not None and item.get("输出格式") == "原文"
                for item in legacy_query
            )
            fallback_ok = all(
                item.get("回退") and not item.get("可用", True)
                and item.get("原文") is not None
                for item in structured_query
            )
            checks.append({
                "name": "切换失败回退",
                "ok": legacy_ok and fallback_ok,
                "detail": (
                    f"切换失败时原文可查={legacy_ok}，新格式请求显式回退原文={fallback_ok}；"
                    f"原文条目={len(legacy_query)}，回退条目={len(structured_query)}"
                ),
                "失败原因": lineage_switch.failure_reason,
                "原文查询": legacy_query,
                "新格式查询": structured_query,
            })
        finally:
            if previous["write"] and previous["read"]:
                lineage_switch.recover()
            else:
                lineage_switch.structured_write_enabled = previous["write"]
                lineage_switch.structured_read_enabled = previous["read"]
                lineage_switch.failure_scope = previous["scope"]
                lineage_switch.failure_reason = previous["reason"]

        # 恢复后分别用原文和新格式再查一次，确认数据本身可读
        legacy_after = self.query_legacy_field_lineage(target)
        structured_after = self.query_structured_field_lineage(target)

        return {
            "golden_id": target,
            "ok": all(check["ok"] for check in checks),
            "checks": checks,
            "queries": {
                "原文": legacy_after,
                "结构化": structured_after,
            },
            "switch_after": lineage_switch.status(),
            "message": (
                "双格式环境核对通过，可进入正式部署"
                if all(check["ok"] for check in checks)
                else "双格式环境核对未通过，请先修复不通过的检查项"
            ),
        }

    def _default_dual_format_golden(self) -> str:
        rows = store.rows(self.MODULE)
        for row in rows:
            if row.get("变换格式") == STRUCTURED_FORMAT and any(
                "|" in str(step.get("值", "")) for step in row.get("变换步骤", [])
            ):
                return row.get("黄金ID", "")
        # 退回任意同时含两种格式的黄金记录
        by_golden: dict[str, set[str]] = {}
        for row in rows:
            by_golden.setdefault(row.get("黄金ID", ""), set()).add(
                row.get("变换格式") or LEGACY_FORMAT)
        for golden, formats in by_golden.items():
            if len(formats) > 1:
                return golden
        return rows[0].get("黄金ID", "") if rows else ""


def _rename_parse_meta(metadata: dict[str, Any]) -> dict[str, Any]:
    """把结构化元数据中的无关字段剔除，保持行字段稳定。"""
    return {
        key: value for key, value in metadata.items()
        if key in {"变换格式", "解析状态", "解析依据", "证据核验", "核验说明", "清洗规则"}
    }
