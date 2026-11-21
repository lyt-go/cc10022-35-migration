"""血缘接口冒烟测试：部署前双格式核对 + 切换失败回退 + 合并报表。"""
from __future__ import annotations

import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from fastapi.testclient import TestClient

from app.main import app
from app.services.lineage_switch import lineage_switch

client = TestClient(app)
GOLDEN = "GR-2026-0001"


def test_dual_format_check_endpoint():
    response = client.get("/api/record_lineage/dual-format-check", params={"golden_id": GOLDEN})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True, payload
    assert len(payload["queries"]["原文"]) == 2
    assert len(payload["queries"]["结构化"]) == 2
    assert lineage_switch.status()["structured_read_enabled"] is True


def test_switch_failure_endpoints():
    try:
        failed = client.post("/api/lineage-switch/simulate-failure", json={"scope": "both"})
        assert failed.status_code == 200
        assert failed.json()["structured_read_enabled"] is False

        legacy = client.get(
            "/api/record_lineage/field-lineage",
            params={"golden_id": GOLDEN, "format": "legacy"},
        ).json()
        assert legacy["count"] == 2
        assert all(item["输出格式"] == "原文" for item in legacy["items"])

        structured = client.get(
            "/api/record_lineage/field-lineage",
            params={"golden_id": GOLDEN, "format": "structured"},
        ).json()
        assert all(item["回退"] for item in structured["items"])
    finally:
        lineage_switch.recover()


def test_merge_report_endpoint():
    response = client.get(f"/api/merge_log/report/{GOLDEN}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "customer.address" in payload["可核验字段"]
    assert "customer.phone" in payload["不可核验字段"]


def test_static_routes_not_shadowed():
    """静态子路径必须优先于 /api/{module}/{entry_id}。"""
    assert client.get("/api/lineage-switch").status_code == 200
    assert client.get("/api/record_lineage?size=1").status_code == 200
    assert client.get("/api/record_lineage/1").status_code == 200


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS: {name}")
                passed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL: {name} -> {exc!r}")
                failed += 1
    print(f"\n结果: {passed}/{passed + failed} 通过")
    assert failed == 0
