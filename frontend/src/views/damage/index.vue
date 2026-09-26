<template>
  <section class="page" data-module="damage">
    <header class="page-head">
      <div>
        <h2>残损登记管理</h2>
        <p class="page-desc">维护残损记录，围绕残损编号、关联箱号、残损类型、残损部位做登记、筛选与状态流转。定责结论以服务端统一口径为准，列表、详情与统计展示同一份结果。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记残损记录</button>
        <button class="btn" type="button" @click="exportRows">导出残损登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>
    <p v-if="partySummary" class="party-summary">责任方分布（与定责结论同口径）：{{ partySummary }}</p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="syncNotice" class="notice-text">{{ syncNotice }}</p>

    <div v-if="draft" class="draft-bar">
      <span class="draft-title">确认定责（{{ draft.label }}）：</span>
      <label class="filter-item">
        <span>责任方</span>
        <input v-model="draft.责任方" placeholder="责任方" />
      </label>
      <label class="filter-item">
        <span>残损类型判定</span>
        <input v-model="draft.残损类型判定" placeholder="残损类型判定" />
      </label>
      <button class="btn primary" type="button" @click="submitDetermination">提交定责</button>
      <button class="btn ghost" type="button" @click="draft = null">取消</button>
      <span class="draft-hint">重复提交只保留最新一条结论</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>定责责任方</th>
          <th>残损类型判定</th>
          <th>结论来源</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.定责结论?.责任方 ?? '—' }}</td>
          <td>{{ row.定责结论?.残损类型判定 ?? '—' }}</td>
          <td>{{ row.定责结论?.结论来源 ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 4" class="empty-state">暂无残损登记数据，可先登记残损记录</td>
        </tr>
      </tbody>
    </table>

    <aside v-if="detail" class="detail-panel">
      <header class="detail-head">
        <strong>残损记录详情（{{ detail.残损编号 ?? detail.id }}）</strong>
        <button class="link" type="button" @click="detail = null">关闭</button>
      </header>
      <dl class="detail-grid">
        <template v-for="column in columns" :key="column">
          <dt>{{ column }}</dt>
          <dd>{{ detail[column] ?? '—' }}</dd>
        </template>
        <dt>当前状态</dt>
        <dd>{{ detail.status ?? '—' }}</dd>
      </dl>
      <div v-if="detail.定责结论" class="conclusion-box">
        <h3>定责结论</h3>
        <p>责任方：{{ detail.定责结论.责任方 }}</p>
        <p>残损类型判定：{{ detail.定责结论.残损类型判定 }}</p>
        <p>定责依据：{{ detail.定责结论.定责依据 }}</p>
        <p>
          结论来源：{{ detail.定责结论.结论来源 }}
          <span v-if="detail.定责结论.定责时间"> · 定责时间：{{ detail.定责结论.定责时间 }}</span>
        </p>
      </div>
    </aside>

    <footer class="page-foot">
      <span>共 {{ total }} 条残损登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface Conclusion {
  责任方: string
  残损类型判定: string
  定责依据: string
  结论来源: string
  定责时间: string | null
}

type Row = Record<string, any> & { id?: number; 定责结论?: Conclusion }

const ENDPOINT = '/api/damage'
const columns = ["残损编号", "关联箱号", "残损类型", "残损部位", "责任方", "发现时间", "登记人员", "残损状态"]
const actions = ["确认定责", "提交闭环", "挂起记录"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([
  { label: '待定责记录', value: 0 },
  { label: '处理中残损', value: 0 },
  { label: '本月闭环数', value: 0 },
])
const partySummary = ref('')
const detail = ref<Row | null>(null)
const draft = ref<{ id: number; label: string; 责任方: string; 残损类型判定: string } | null>(null)
const syncNotice = ref('')
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '残损记录登记入口尚未接入审批流'
}

// 结论不一致时以服务端为准：本地未提交的草稿与服务端结论不同的，丢弃草稿并说明原因
function syncDraftWithServer(serverRow: Row) {
  const conclusion = serverRow.定责结论
  if (!draft.value || !conclusion || draft.value.id !== Number(serverRow.id)) return
  if (draft.value.责任方 !== conclusion.责任方 || draft.value.残损类型判定 !== conclusion.残损类型判定) {
    draft.value = {
      id: Number(serverRow.id),
      label: String(serverRow.残损编号 ?? serverRow.id),
      责任方: conclusion.责任方,
      残损类型判定: conclusion.残损类型判定,
    }
    syncNotice.value = `残损记录 ${serverRow.残损编号 ?? serverRow.id} 的本地草稿与服务端结论不一致，已按服务端为准：定责依据只保留服务端一份口径`
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('残损记录详情读取失败')
    }
    detail.value = (await response.json()) as Row
    syncDraftWithServer(detail.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损记录详情读取失败'
  }
}

function runAction(action: string, row: Row) {
  if (action === '确认定责') {
    const conclusion = row.定责结论
    draft.value = {
      id: Number(row.id),
      label: String(row.残损编号 ?? row.id),
      责任方: conclusion?.责任方 ?? '',
      残损类型判定: conclusion?.残损类型判定 ?? '',
    }
    return
  }
  void postAction(row, { action })
}

async function submitDetermination() {
  if (!draft.value) return
  const { id, 责任方, 残损类型判定 } = draft.value
  await postAction({ id }, { action: '确认定责', 责任方, 残损类型判定 })
  draft.value = null
}

async function postAction(row: Row, values: Record<string, string>) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(values),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.message ?? '残损登记动作未生效，请稍后重试')
    }
    if (detail.value && Number(detail.value.id) === Number(row.id)) {
      await openDetail(row)
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损登记操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('残损记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    rows.value.forEach(syncDraftWithServer)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损登记列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('残损统计读取失败')
    }
    const payload = await response.json()
    const byStatus = payload.状态统计 ?? {}
    stats.value = [
      { label: '待定责记录', value: byStatus['待定责'] ?? 0 },
      { label: '处理中残损', value: byStatus['处理中'] ?? 0 },
      { label: '本月闭环数', value: payload.本月闭环数 ?? 0 },
    ]
    partySummary.value = Object.entries(payload.责任方分布 ?? {})
      .map(([party, count]) => `${party} ${count}`)
      .join(' · ')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损统计读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>

<style scoped>
.party-summary { color: var(--muted); font-size: 12px; margin: 0 0 12px; }
.notice-text { color: #b45309; font-size: 12px; margin: 0 0 8px; }
.draft-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 12px; }
.draft-title { font-size: 13px; }
.draft-hint { color: var(--muted); font-size: 12px; }
.detail-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-top: 12px; }
.detail-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.detail-grid { display: grid; grid-template-columns: 120px 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.conclusion-box { border-top: 1px solid var(--border); margin-top: 10px; padding-top: 10px; font-size: 13px; }
.conclusion-box h3 { font-size: 14px; margin: 0 0 6px; }
.conclusion-box p { margin: 2px 0; }
</style>
