/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 血缘步骤：值与顺序一一对应，值原样来自写入方或迁移解析。 */
export type LineageStep = {
  顺序: number
  值: string
  说明?: string
}

/** 字段血缘条目：结构化视图或原文回退视图的并集。 */
export type FieldLineageItem = {
  血缘编号: string
  黄金ID: string
  来源记录: string
  来源系统: string
  字段路径: string
  变换格式: string
  输出格式: string
  原文: string
  步骤: LineageStep[]
  步骤数: number
  解析状态: string
  解析依据: string
  证据核验: string
  核验说明?: string
  未迁移原因?: string
  可用?: boolean
  回退?: boolean
  可完成合并证据核验: boolean
}

export type LineageQueryResult = {
  golden_id: string
  format: string
  count: number
  items: FieldLineageItem[]
  switch: LineageSwitchStatus
}

export type LineageSwitchStatus = {
  structured_write_enabled: boolean
  structured_read_enabled: boolean
  failure_scope: string
  failure_reason: string
  changed_at: string
  raw_lineage_available: boolean
  message: string
}

export type MergeEvidenceAudit = {
  golden_id: string
  合并记录: string | null
  来源记录: string | null
  fields: {
    字段路径: string
    可完成合并证据核验: boolean
    结论: string
    原因: string
    条目: FieldLineageItem[]
  }[]
  可核验字段: string[]
  不可核验字段: string[]
  summary: {
    total_fields: number
    verifiable: number
    blocked: number
    conclusion: string
  }
}

export type DualFormatCheck = {
  golden_id: string
  ok: boolean
  message: string
  checks: {
    name: string
    ok: boolean
    detail: string
  }[]
  queries: {
    原文: FieldLineageItem[]
    结构化: FieldLineageItem[]
  }
}

export type MigrationResult = {
  golden_id: string | null
  scanned: number
  migrated: number
  unproven: number
  already_structured: number
  message: string
}
