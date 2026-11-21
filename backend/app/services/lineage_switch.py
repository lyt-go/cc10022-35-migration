"""结构化血缘切换开关：支持在部署前演练结构写入/读取失败。

切换失败时不能影响旧字段血缘的查询能力，本模块只记录“结构化链路是否可用”，
领域服务据此选择结构化视图或原文回退，并在返回结果里明确标注。
"""
from __future__ import annotations

import datetime
from typing import Any


class LineageSwitchState:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.structured_write_enabled = True
        self.structured_read_enabled = True
        self.failure_scope = ""
        self.failure_reason = ""
        self.changed_at = ""
        self.history: list[dict[str, Any]] = []

    def _log(self, action: str, **extra: Any) -> None:
        self.history.append({
            "action": action,
            "structured_write_enabled": self.structured_write_enabled,
            "structured_read_enabled": self.structured_read_enabled,
            "failure_scope": self.failure_scope,
            "failure_reason": self.failure_reason,
            "at": datetime.datetime.utcnow().isoformat(),
            **extra,
        })

    def simulate_failure(self, scope: str = "write", reason: str = "部署演练：模拟结构化血缘切换失败") -> dict[str, Any]:
        scope = scope if scope in {"write", "read", "both"} else "write"
        self.failure_scope = scope
        self.failure_reason = reason
        # 只有“仅读失败”时写入仍可用；只有“仅写失败”时读取仍可用；“both”两者都不可用
        self.structured_write_enabled = scope == "read"
        self.structured_read_enabled = scope == "write"
        self.changed_at = datetime.datetime.utcnow().isoformat()
        self._log("simulate_failure", scope=scope)
        return self.status()

    def recover(self) -> dict[str, Any]:
        self.structured_write_enabled = True
        self.structured_read_enabled = True
        self.failure_scope = ""
        self.failure_reason = ""
        self.changed_at = datetime.datetime.utcnow().isoformat()
        self._log("recover")
        return self.status()

    def status(self) -> dict[str, Any]:
        write_failure = not self.structured_write_enabled
        read_failure = not self.structured_read_enabled
        return {
            "structured_write_enabled": self.structured_write_enabled,
            "structured_read_enabled": self.structured_read_enabled,
            "failure_scope": self.failure_scope,
            "failure_reason": self.failure_reason,
            "changed_at": self.changed_at,
            "raw_lineage_available": True,
            "message": (
                "结构化血缘链路正常"
                if not write_failure and not read_failure
                else "结构化链路不可用，已回退原文；旧字段血缘仍可查询"
            ),
        }


lineage_switch = LineageSwitchState()
