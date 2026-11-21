"""结构化字段血缘迁移与切换演练测试。

覆盖：
1. 新写入表达式含竖线时原样保留、顺序正确；
2. 旧竖线记录能拆则拆、不能证明边界则保留原文并说明；
3. 同一合并事件双格式（电话旧链 / 地址新规则）的审计结论；
4. 模拟切换失败后原文查询仍可用、新格式查询显式回退；
5. 部署前双格式核对包含旧链复核、含竖线新步骤和切换演练。
"""
from __future__ import annotations

import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.services.lineage_switch import lineage_switch
from app.services.lineage_transform import (
    PARSE_OK,
    PARSE_PROVEN,
    PARSE_UNPROVEN,
    parse_legacy_transform,
)
from app.services.merge_log import MergeLogService
from app.services.record_lineage import RecordLineageService
from app.store import store

GOLDEN = "GR-2026-0001"
CHAIN_GOLDEN = "GR-lineage-test-001"


def _reset_switch() -> None:
    lineage_switch.recover()


def test_new_expression_keeps_pipe_and_order():
    """新写入：一条表达式含竖线时原样保留，不被拆分，顺序与入参一致。"""
    _reset_switch()
    svc = RecordLineageService()
    steps = ["trim", "regex(^1(3|5|8)\\d{9}$)", "mask:中间四位"]
    result = svc.record_field_lineage(
        CHAIN_GOLDEN, "SRC-NEW-1", "CRM", "customer.phone", steps)
    assert result["ok"] and not result["degraded"], result
    stored = result["lineage"]["步骤"]
    assert [s["值"] for s in stored] == steps, stored
    assert [s["顺序"] for s in stored] == [1, 2, 3], stored
    assert result["lineage"]["含竖线"] if "含竖线" in result["lineage"] else True

    # 再次通过查询确认不是展示层临时拼接
    queried = svc.query_field_lineage(CHAIN_GOLDEN)
    assert [s["值"] for s in queried[0]["步骤"]] == steps
    assert queried[0]["可完成合并证据核验"] is True


def test_new_single_string_is_one_step():
    """新写入：整条字符串即使含竖线也必须视为一步。"""
    _reset_switch()
    svc = RecordLineageService()
    result = svc.record_field_lineage(
        CHAIN_GOLDEN, "SRC-NEW-2", "ERP", "customer.name", "a|b|c")
    stored = result["lineage"]["步骤"]
    assert len(stored) == 1 and stored[0]["值"] == "a|b|c", stored


def test_legacy_ambiguous_keeps_raw():
    """旧格式：括号内竖线无法证明边界时保留原文并说明原因。"""
    parsed = parse_legacy_transform("trim|format_phone|^(13|15|18)\\d{9}$")
    assert parsed["解析状态"] == PARSE_UNPROVEN
    assert parsed["步骤"] == []
    assert parsed["证据核验"] == "不可核验"
    assert "无法证明" in parsed["解析依据"]


def test_legacy_plain_is_split():
    """旧格式：无歧义时按竖线切分，但边界仍标记为推定。"""
    parsed = parse_legacy_transform("trim|lower|标准化")
    assert parsed["解析状态"] == PARSE_OK
    assert [s["值"] for s in parsed["步骤"]] == ["trim", "lower", "标准化"]
    assert parsed["证据核验"] == "不可核验"


def test_legacy_single_no_pipe_is_proven():
    parsed = parse_legacy_transform("仅一步")
    assert parsed["解析状态"] == PARSE_PROVEN
    assert [s["值"] for s in parsed["步骤"]] == ["仅一步"]


def test_migration_is_idempotent_and_keeps_raw():
    """迁移：重复执行不会重复拆分，原文保持原样。"""
    _reset_switch()
    svc = RecordLineageService()
    svc.migrate_legacy_lineage(GOLDEN)
    first = svc.migrate_legacy_lineage(GOLDEN)
    second = svc.migrate_legacy_lineage(GOLDEN)
    assert second["already_structured"] >= first["already_structured"]

    row = next(r for r in store.rows("record_lineage") if r.get("id") == 101)
    assert row["原文"] == "trim|format_phone|^(13|15|18)\\d{9}$"
    assert row["变换记录"] == "trim|format_phone|^(13|15|18)\\d{9}$"
    assert row["解析状态"] == PARSE_UNPROVEN
    assert row.get("未迁移原因")
    assert row["变换步骤"] == []


def test_mixed_merge_evidence_audit():
    """同一合并事件：电话不可核验、地址可核验。"""
    _reset_switch()
    svc = RecordLineageService()
    svc.migrate_legacy_lineage(GOLDEN)
    audit = svc.audit_merge_evidence(GOLDEN)
    assert audit["合并记录"] == "MERGE-20261101090000"
    assert "customer.address" in audit["可核验字段"]
    assert "customer.phone" in audit["不可核验字段"]
    phone = next(f for f in audit["fields"] if f["字段路径"] == "customer.phone")
    address = next(f for f in audit["fields"] if f["字段路径"] == "customer.address")
    assert phone["可完成合并证据核验"] is False
    assert phone["条目"][0]["原文"] == "trim|format_phone|^(13|15|18)\\d{9}$"
    assert address["可完成合并证据核验"] is True
    assert [s["值"] for s in address["条目"][0]["步骤"]] == [
        "trim", "remove_spaces", "地址补全（省|市|区）", "标准地址编码",
    ]


def test_merge_report_links_actual_steps():
    """合并报表：按字段给出实际步骤与解析依据，地址步骤含竖线且完整。"""
    _reset_switch()
    svc = RecordLineageService()
    svc.migrate_legacy_lineage(GOLDEN)
    report = MergeLogService().export_merge_report(GOLDEN)
    address_rows = [row for row in report["明细"] if row["字段路径"] == "customer.address"]
    assert len(address_rows) == 1
    assert [s["值"] for s in address_rows[0]["步骤"]][2] == "地址补全（省|市|区）"
    assert address_rows[0]["可完成合并证据核验"] is True
    assert "customer.phone" in report["不可核验字段"]


def test_switch_failure_keeps_raw_queryable():
    """切换失败：原文查询可用，结构化查询显式回退，不抛错。"""
    svc = RecordLineageService()
    try:
        lineage_switch.simulate_failure(scope="both", reason="测试切换失败")
        legacy = svc.query_field_lineage(GOLDEN, output_format="legacy")
        assert len(legacy) == 2
        assert all(item["输出格式"] == "原文" for item in legacy)
        assert any(item["原文"] == "trim|format_phone|^(13|15|18)\\d{9}$" for item in legacy)

        structured = svc.query_field_lineage(GOLDEN, output_format="structured")
        assert structured and all(item.get("回退") for item in structured)
        assert all(item["可用"] is False for item in structured)
        assert all(item["原文"] for item in structured)
        assert all(item["可完成合并证据核验"] is False for item in structured)
    finally:
        lineage_switch.recover()


def test_write_failure_degrades_then_recovers():
    """写入切换失败：保留原文；恢复后迁移回结构化且不拆坏表达式。"""
    svc = RecordLineageService()
    golden = "GR-lineage-fail-001"
    try:
        lineage_switch.simulate_failure(scope="write", reason="测试写入失败")
        degraded = svc.record_field_lineage(
            golden, "SRC-F-1", "CRM", "customer.alias", ["甲|乙", "丙"])
        assert degraded["degraded"] is True
        assert degraded["lineage"]["原文"] == "甲|乙|丙"
    finally:
        lineage_switch.recover()

    migrated = svc.migrate_legacy_lineage(golden)
    assert migrated["migrated"] == 1
    view = svc.query_field_lineage(golden)
    assert [s["值"] for s in view[0]["步骤"]] == ["甲|乙", "丙"]


def test_dual_format_precheck():
    """部署前核对：旧链 + 含竖线新步骤 + 切换演练 + 两种查询。"""
    _reset_switch()
    svc = RecordLineageService()
    svc.migrate_legacy_lineage(GOLDEN)
    report = svc.run_dual_format_check(GOLDEN)
    assert report["ok"] is True, report
    names = [check["name"] for check in report["checks"]]
    assert names == ["旧链回读", "含竖线新步骤原样保留", "切换失败回退"]
    assert lineage_switch.status()["structured_write_enabled"] is True
    assert lineage_switch.status()["structured_read_enabled"] is True
    assert len(report["queries"]["原文"]) == 2
    assert len(report["queries"]["结构化"]) == 2
    assert any(
        step["值"] == "地址补全（省|市|区）"
        for item in report["queries"]["结构化"] for step in item["步骤"]
    )


def _run() -> None:
    tests = [(name, obj) for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as exc:  # noqa: BLE001 - 测试入口需要打印失败原因
            print(f"  FAIL: {name} -> {exc!r}")
            failed += 1
    print(f"\n{'=' * 60}\n结果: {passed}/{len(tests)} 通过, {failed} 失败")
    assert failed == 0, f"{failed} 条血缘测试失败！"


if __name__ == "__main__":
    _run()
