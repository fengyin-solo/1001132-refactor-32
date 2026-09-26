<template>
  <section class="page" data-module="damage">
    <header class="page-head">
      <div>
        <h2>残损登记管理</h2>
        <p class="page-desc">维护残损记录，围绕残损编号、关联箱号、残损类型、残损部位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记残损记录</button>
        <button class="btn" type="button" @click="exportRows">导出残损登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>定责结论</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">
              {{ row['定责结论'] ?? '待定责' }}
            </button>
            <small v-if="row['建议责任方']" class="muted-text">（建议：{{ row['建议责任方'] }}，待确认）</small>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="onAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!availableActions(row).length" class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无残损登记数据，可先登记残损记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条残损登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <header class="modal-head">
          <h3>残损记录详情 · {{ detail['残损编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="item in detailFields" :key="item">
            <dt>{{ item }}</dt>
            <dd>{{ detail[item] ?? '—' }}</dd>
          </template>
          <dt>建议责任方</dt>
          <dd>{{ detail['建议责任方'] ? `${detail['建议责任方']}（待人工确认）` : '—' }}</dd>
          <dt>定责依据</dt>
          <dd>{{ detail['定责依据'] || '尚无统一口径匹配，保持待定责' }}</dd>
          <dt>定责说明</dt>
          <dd>{{ detail['定责说明'] || '—' }}</dd>
          <dt>结论版本</dt>
          <dd>v{{ detail['定责版本'] ?? 0 }}</dd>
        </dl>
        <p class="modal-tip">结论由服务端按统一口径出具，本页与列表、统计、导出取自同一份结果。</p>
      </div>
    </div>

    <div v-if="liabilityForm.open" class="modal-mask" @click.self="closeLiability">
      <form class="modal" @submit.prevent="submitLiability">
        <header class="modal-head">
          <h3>确认定责 · {{ liabilityForm.row?.['残损编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeLiability">取消</button>
        </header>
        <p class="modal-tip">责任方与残损类型由服务端统一口径判定；如与提交值不一致，以服务端结论为准并说明原因。</p>
        <label class="form-item">
          <span>残损类型（事实描述）</span>
          <input v-model="liabilityForm.damageType" placeholder="如：箱体凹陷、货物渗漏" />
        </label>
        <label class="form-item">
          <span>残损部位</span>
          <input v-model="liabilityForm.part" placeholder="如：左侧箱门" />
        </label>
        <label class="form-item">
          <span>初判责任方（可选，仅供核对）</span>
          <input v-model="liabilityForm.clientParty" placeholder="与服务端口径不一致时将被修正" />
        </label>
        <footer class="modal-foot">
          <button class="btn primary" type="submit">提交定责</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/damage'
// 列表只展示登记字段；定责结论单独一列，数据全部来自服务端，前端不再自行判定。
const columns = ["残损编号", "关联箱号", "残损类型", "残损部位", "责任方", "发现时间", "登记人员"]
const detailFields = ["残损编号", "关联箱号", "残损类型", "标准残损类型", "残损部位", "责任方", "定责状态", "定责结论", "发现时间", "登记人员"]
const statsMeta = [
  { key: '待定责记录', label: '待定责记录' },
  { key: '处理中残损', label: '处理中残损' },
  { key: '本月闭环数', label: '本月闭环数' },
] as const

// 当前状态允许的动作与后端 STATUS_ACTIONS 保持一致；前端只做按钮收敛，真正的拦截仍在服务端。
const STATUS_ACTIONS: Record<string, string[]> = {
  '待定责': ['确认定责'],
  '已定责': ['确认定责', '提交闭环', '挂起记录'],
  '处理中': ['提交闭环'],
  '已挂起': ['确认定责'],
  '已闭环': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const statCards = ref(statsMeta.map((item) => ({ label: item.label, value: 0 })))
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)
const liabilityForm = reactive({
  open: false,
  row: null as Row | null,
  damageType: '',
  part: '',
  clientParty: '',
})

function formatCell(row: Row, column: string): string {
  const value = row[column]
  if (column === '责任方') return String(value ?? '待定责')
  return String(value ?? '—')
}

function availableActions(row: Row): string[] {
  return STATUS_ACTIONS[String(row.status ?? '')] ?? []
}

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

async function openDetail(row: Row) {
  errorMessage.value = ''
  // 详情重新向服务端取单条结果，保证看到的就是统一口径的最新结论。
  const response = await request(`${ENDPOINT}/${row.id}`)
  if (!response.ok) {
    errorMessage.value = '残损记录详情读取失败'
    return
  }
  detail.value = await response.json()
}

function closeDetail() {
  detail.value = null
}

function onAction(action: string, row: Row) {
  if (action === '确认定责') {
    liabilityForm.open = true
    liabilityForm.row = row
    liabilityForm.damageType = String(row['残损类型'] ?? '')
    liabilityForm.part = String(row['残损部位'] ?? '')
    liabilityForm.clientParty = ''
    return
  }
  void runAction(action, row)
}

function closeLiability() {
  liabilityForm.open = false
  liabilityForm.row = null
}

async function submitLiability() {
  if (!liabilityForm.row) return
  const values: Record<string, string> = {
    action: '确认定责',
    残损类型: liabilityForm.damageType,
    残损部位: liabilityForm.part,
    责任方: liabilityForm.clientParty,
  }
  await postAction(liabilityForm.row.id, values)
  closeLiability()
}

async function runAction(action: string, row: Row) {
  await postAction(row.id, { action })
}

async function postAction(id: string | number | null, values: Record<string, string>) {
  if (id === null) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.detail || payload?.message || '残损登记动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message || '操作已生效'
    // 重新拉列表、统计，结论只认刷新后服务端返回的这一份。
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损登记操作失败'
    await reload()
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = await response.json()
    statCards.value = statsMeta.map((item) => ({ label: item.label, value: Number(data[item.key] ?? 0) }))
  } catch {
    // 统计取不到不阻断列表，卡片保持上一次的值。
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '残损登记列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.muted-text { color: var(--muted); }
.notice-text { color: #b54708; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-tip { font-size: 12px; color: var(--muted); margin: 8px 0; }
.detail-grid { display: grid; grid-template-columns: 96px 1fr; gap: 6px 12px; margin: 0; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; margin-top: 8px; }
</style>
