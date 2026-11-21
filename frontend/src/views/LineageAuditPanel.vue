<template>
  <section class="lineage-panel" data-testid="lineage-panel">
    <header class="lineage-head">
      <div>
        <h3>字段血缘核验</h3>
        <p class="page-desc">
          逐字段核对变换步骤与解析依据；旧拼接格式无法证明边界时保留原文并说明原因。
        </p>
      </div>
      <span class="switch-pill" :class="{ down: !(status?.structured_read_enabled && status?.structured_write_enabled) }" data-testid="switch-pill">
        {{ status?.message ?? '读取切换状态…' }}
      </span>
    </header>

    <form class="filter-bar" @submit.prevent="loadAudit">
      <label class="filter-item">
        <span>黄金ID</span>
        <input v-model="goldenId" data-testid="golden-input" placeholder="如 GR-2026-0001" />
      </label>
      <button class="btn primary" data-testid="audit" type="submit">核验合并证据</button>
      <button class="btn" data-testid="migrate" type="button" @click="runMigration">迁移旧格式血缘</button>
      <button class="btn ghost" data-testid="precheck" type="button" @click="runPrecheck">部署前双格式核对</button>
    </form>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    <p v-if="migrationMessage" class="hint-text" data-testid="migration-message">{{ migrationMessage }}</p>

    <div v-if="precheck" class="precheck" data-testid="precheck-result">
      <strong>{{ precheck.ok ? '核对通过' : '核对未通过' }}：{{ precheck.message }}</strong>
      <ul>
        <li v-for="check in precheck.checks" :key="check.name" :class="check.ok ? 'check-ok' : 'check-bad'">
          {{ check.ok ? '✓' : '✗' }} {{ check.name }} — {{ check.detail }}
        </li>
      </ul>
    </div>

    <div v-if="audit" class="audit-summary" data-testid="audit-summary">
      <article class="stat-card">
        <span class="stat-label">检查字段</span>
        <strong class="stat-value">{{ audit.summary.total_fields }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可完成合并证据核验</span>
        <strong class="stat-value ok-text">{{ audit.summary.verifiable }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">不可核验</span>
        <strong class="stat-value bad-text">{{ audit.summary.blocked }}</strong>
      </article>
      <p class="audit-conclusion">{{ audit.summary.conclusion }}</p>
    </div>

    <table v-if="audit" class="data-table lineage-table">
      <thead>
        <tr>
          <th>字段路径</th>
          <th>来源</th>
          <th>格式</th>
          <th>步骤（顺序 / 值）</th>
          <th>解析依据</th>
          <th>证据核验</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="field in audit.fields" :key="field.字段路径">
          <tr
            v-for="item in field.条目"
            :key="`${field.字段路径}-${item.血缘编号}`"
            :data-testid="`lineage-${item.血缘编号}`"
            :data-verifiable="field.可完成合并证据核验 ? 'yes' : 'no'"
          >
            <td>{{ field.字段路径 }}</td>
            <td>{{ item.来源系统 }} / {{ item.来源记录 }}</td>
            <td>{{ item.变换格式 }}</td>
            <td>
              <ol v-if="item.步骤.length" class="step-list">
                <li v-for="step in item.步骤" :key="step.顺序">
                  <span class="step-seq">{{ step.顺序 }}</span>
                  <code class="step-value">{{ step.值 }}</code>
                </li>
              </ol>
              <span v-else class="raw-text">
                未拆分：<code>{{ item.原文 }}</code>
              </span>
            </td>
            <td class="basis-text">{{ item.解析依据 }}</td>
            <td>
              <span :class="field.可完成合并证据核验 ? 'badge ok' : 'badge bad'">
                {{ field.可完成合并证据核验 ? '可核验' : '不可核验' }}
              </span>
              <p v-if="item.未迁移原因" class="reason-text">{{ item.未迁移原因 }}</p>
            </td>
          </tr>
        </template>
        <tr v-if="!audit.fields.length">
          <td colspan="6" class="empty-state">该黄金记录没有可核验的字段血缘</td>
        </tr>
      </tbody>
    </table>

    <label class="filter-item switch-form">
      <span>切换演练</span>
      <select v-model="scope" data-testid="switch-scope">
        <option value="write">仅结构化写入失败</option>
        <option value="read">仅结构化读取失败</option>
        <option value="both">读写同时失败</option>
      </select>
    </label>
    <button class="btn" data-testid="simulate" type="button" @click="simulate">模拟切换失败</button>
    <button class="btn ghost" data-testid="recover" type="button" @click="recover">恢复结构化链路</button>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  auditMergeEvidence,
  loadSwitchStatus,
  migrateLegacyLineage,
  recoverSwitch,
  runDualFormatCheck,
  simulateSwitchFailure,
} from '@/api/lineage-service'
import type {
  DualFormatCheck,
  LineageSwitchStatus,
  MergeEvidenceAudit,
} from '@/data/types'

const props = defineProps<{ goldenId?: string }>()
const goldenId = ref(props.goldenId ?? 'GR-2026-0001')
const audit = ref<MergeEvidenceAudit | null>(null)
const precheck = ref<DualFormatCheck | null>(null)
const status = ref<LineageSwitchStatus | null>(null)
const migrationMessage = ref('')
const errorMessage = ref('')
const scope = ref<'write' | 'read' | 'both'>('both')

async function loadStatus() {
  try {
    status.value = await loadSwitchStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '切换状态读取失败'
  }
}

async function loadAudit() {
  errorMessage.value = ''
  precheck.value = null
  try {
    audit.value = await auditMergeEvidence(goldenId.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '合并证据核验失败'
  }
}

async function runMigration() {
  errorMessage.value = ''
  try {
    const result = await migrateLegacyLineage(goldenId.value.trim())
    migrationMessage.value = result.message
    await loadAudit()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '迁移失败'
  }
}

async function runPrecheck() {
  errorMessage.value = ''
  try {
    precheck.value = await runDualFormatCheck(goldenId.value.trim())
    await loadStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '部署前核对失败'
  }
}

async function simulate() {
  errorMessage.value = ''
  try {
    status.value = await simulateSwitchFailure(scope.value)
    await loadAudit()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模拟切换失败未生效'
  }
}

async function recover() {
  errorMessage.value = ''
  try {
    status.value = await recoverSwitch()
    await loadAudit()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '恢复失败'
  }
}

onMounted(async () => {
  await loadStatus()
  await loadAudit()
})
</script>

<style scoped>
.lineage-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 16px; }
.lineage-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.lineage-head h3 { margin: 0 0 4px; font-size: 15px; }
.switch-pill { font-size: 12px; padding: 4px 10px; border-radius: 999px; background: #e8f5ec; color: #157347; }
.switch-pill.down { background: #fdecea; color: #b42318; }
.audit-summary { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 12px 0; }
.audit-conclusion { font-size: 13px; color: var(--muted); margin: 0; }
.step-list { margin: 0; padding-left: 18px; }
.step-value { background: #f4f6f9; padding: 1px 5px; border-radius: 4px; }
.step-seq { color: var(--muted); margin-right: 4px; }
.raw-text { font-size: 12px; color: var(--muted); }
.basis-text { font-size: 12px; color: #475467; max-width: 320px; }
.reason-text { font-size: 12px; color: #b42318; margin: 4px 0 0; }
.badge { font-size: 12px; padding: 2px 8px; border-radius: 999px; }
.badge.ok { background: #e8f5ec; color: #157347; }
.badge.bad { background: #fdecea; color: #b42318; }
.ok-text { color: #157347; }
.bad-text { color: #b42318; }
.hint-text { font-size: 12px; color: #157347; }
.precheck { margin: 10px 0; font-size: 13px; }
.precheck ul { margin: 6px 0 0; padding-left: 18px; }
.check-ok { color: #157347; }
.check-bad { color: #b42318; }
.switch-form { margin-top: 12px; }
</style>
