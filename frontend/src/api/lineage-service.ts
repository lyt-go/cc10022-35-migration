import { fetchJson, request } from './client'
import type {
  DualFormatCheck,
  LineageQueryResult,
  LineageSwitchStatus,
  MergeEvidenceAudit,
  MigrationResult,
} from '@/data/types'

/** 把旧竖线拼接血缘迁移为结构化字段血缘（幂等）。 */
export async function migrateLegacyLineage(goldenId?: string): Promise<MigrationResult> {
  const response = await request('/api/record_lineage/legacy-migration', {
    method: 'POST',
    body: JSON.stringify({ golden_id: goldenId ?? null }),
  })
  if (!response.ok) throw new Error('旧格式血缘迁移失败')
  return (await response.json()) as MigrationResult
}

/** 按格式查询字段血缘：legacy 不受切换开关影响。 */
export async function queryFieldLineage(
  goldenId: string,
  format: 'auto' | 'legacy' | 'structured' = 'auto',
): Promise<LineageQueryResult> {
  const query = new URLSearchParams({ golden_id: goldenId, format })
  return await fetchJson<LineageQueryResult>(`/api/record_lineage/field-lineage?${query}`)
}

/** 审计员视图：逐字段判断能否完成合并证据核验。 */
export async function auditMergeEvidence(goldenId: string): Promise<MergeEvidenceAudit> {
  return await fetchJson<MergeEvidenceAudit>(
    `/api/record_lineage/merge-evidence/${encodeURIComponent(goldenId)}`,
  )
}

/** 部署前核对：旧链、含竖线新步骤、切换失败回退与两种查询。 */
export async function runDualFormatCheck(goldenId?: string): Promise<DualFormatCheck> {
  const query = goldenId ? `?${new URLSearchParams({ golden_id: goldenId })}` : ''
  return await fetchJson<DualFormatCheck>(`/api/record_lineage/dual-format-check${query}`)
}

export async function loadSwitchStatus(): Promise<LineageSwitchStatus> {
  return await fetchJson<LineageSwitchStatus>('/api/lineage-switch')
}

export async function simulateSwitchFailure(scope: 'write' | 'read' | 'both'): Promise<LineageSwitchStatus> {
  const response = await request('/api/lineage-switch/simulate-failure', {
    method: 'POST',
    body: JSON.stringify({ scope, reason: '前端演练：模拟结构化血缘切换失败' }),
  })
  if (!response.ok) throw new Error('模拟切换失败未生效')
  return (await response.json()) as LineageSwitchStatus
}

export async function recoverSwitch(): Promise<LineageSwitchStatus> {
  const response = await request('/api/lineage-switch/recover', { method: 'POST' })
  if (!response.ok) throw new Error('恢复结构化链路失败')
  return (await response.json()) as LineageSwitchStatus
}
