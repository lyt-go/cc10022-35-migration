# 主数据清洗与黄金记录平台

面向多源主数据的匹配识别、冲突消解、合并清洗与黄金记录管理的主数据治理平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 来源系统注册 | `source_system` | 来源系统 | 系统编号、系统名称、系统类型 |
| 实体模型定义 | `entity_model` | 实体模型 | 模型编号、模型名称、业务域 |
| 匹配规则引擎 | `match_rule` | 匹配规则 | 规则编号、实体模型、匹配字段 |
| 疑似重复簇 | `dup_cluster` | 重复簇 | 簇编号、实体模型、簇大小 |
| 合并追溯日志 | `merge_log` | 合并记录 | 记录编号、黄金ID、来源记录 |
| 黄金记录管理 | `golden_record` | 黄金记录 | 黄金ID、实体模型、关联来源 |
| 字段标准化清洗 | `field_cleanse` | 清洗规则 | 规则编号、实体模型、目标字段 |
| 优胜策略配置 | `survivorship_rule` | 优胜策略 | 策略编号、实体模型、选择字段 |
| 数据入库规则 | `data_import_rule` | 入库规则 | 规则编号、来源系统、实体模型 |
| 批次导入管理 | `import_batch` | 导入批次 | 批次编号、来源系统、实体模型 |
| 记录级血缘 | `record_lineage` | 血缘记录 | 血缘编号、黄金ID、来源记录 |
| 主数据分发同步 | `mdm_sync` | 同步配置 | 配置编号、黄金实体、目标系统 |
| 黄金记录版本 | `mdm_version` | 版本记录 | 版本编号、黄金ID、版本号 |
| 自动匹配任务 | `auto_match_job` | 匹配任务 | 任务编号、实体模型、匹配规则 |
| 主数据质量统计 | `mdm_quality` | 质量统计 | 统计编号、实体模型、完备率 |
| 参考数据管理 | `mdm_reference` | 参考数据 | 数据编号、数据类别、标准编码 |
| 主数据查询接口 | `mdm_api` | 查询接口 | 接口编号、实体模型、查询字段 |
| 主数据治理看板 | `mdm_dashboard` | 看板配置 | 看板编号、看板名称、监控实体 |

## 结构化字段血缘

记录级血缘的权威数据是 `变换步骤`（按 `顺序` 排列的 `值` 列表），
`变换记录` 只作展示/兼容：

- **新写入**：`变换记录` 或 `变换步骤` 交给 `record_field_lineage` 时按原样保存，
  含竖线的表达式也是一条步骤，不会被拼接或切分；
- **旧记录迁移**：`migrate_legacy_lineage` 按旧竖线格式解析。能证明边界时拆分并标记
  “推定/已证明”；出现括号/引号不闭合、空段、悬挂转义等歧义时，保留 `原文`、
  步骤留空并写入 `未迁移原因`，不猜测；
- **切换失败**：模拟结构化读写失败后，`format=legacy` 的原文查询始终可用，
  `format=structured` 返回 `回退=true` 的原文对象并在 `解析依据` 说明原因；
- **合并证据核验**：`audit_merge_evidence` 逐字段给出能否完成合并证据核验；
  合并报表 `merge_log/report/{golden_id}` 输出实际步骤、原文与解析依据。

示例数据 `GR-2026-0001` 是一次合并事件的双格式样本：电话来自旧拼接链路
（边界不可证明，不可核验），地址来自新清洗规则（结构化步骤可核验）。

### 相关接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/record_lineage/legacy-migration` | 迁移旧竖线血缘（幂等） |
| GET | `/api/record_lineage/field-lineage?golden_id=&format=auto\|legacy\|structured` | 按格式查询 |
| GET | `/api/record_lineage/merge-evidence/{golden_id}` | 审计员逐字段核验视图 |
| GET | `/api/record_lineage/dual-format-check` | 部署前双格式核对 |
| GET | `/api/merge_log/report/{golden_id}` | 合并报表（步骤 + 解析依据） |
| POST | `/api/lineage-switch/simulate-failure` | 演练切换失败（`scope=write\|read\|both`） |
| POST | `/api/lineage-switch/recover` | 恢复结构化链路 |
| GET | `/api/lineage-switch/history` | 切换/演练历史 |

### 部署前核对

```bash
curl -s 'http://127.0.0.1:8000/api/record_lineage/dual-format-check' | python3 -m json.tool
```

核对项：旧链回读、含竖线新步骤原样保留、切换失败回退；结束后自动恢复开关，
并分别返回 `queries.原文` 与 `queries.结构化` 两套查询结果。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数仓与数据湖
