"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import lineage_ops, resource

# 静态子路径必须先于资源路由注册，避免被 /api/{module}/{entry_id} 抢先匹配。
ROUTERS = [lineage_ops, resource]
