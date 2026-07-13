<template>
  <div class="app-container">
    <div class="tm-header">
      <h3>遥测监控 · {{ tableName }} (0x{{ tmType }})</h3>
      <el-tag :type="connected ? 'success' : 'danger'">{{ connected ? '已连接' : '未连接' }}</el-tag>
      <span v-if="dataTs" class="tm-ts">数据时间: {{ dataTs }}</span>
      <span class="tm-ts">刷新时间: {{ refreshTs }}</span>
      <el-select v-model="deviceId" style="width: 220px; margin-left: 12px" @change="onDeviceChange">
        <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
      </el-select>
    </div>
    <el-table
      :data="rows"
      v-loading="initialLoading"
      row-key="id"
      border
      stripe
      height="calc(100vh - 180px)"
    >
      <el-table-column label="编号" width="100">
        <template #default="{ row }">
          <el-tooltip
            v-if="defById[row.id]"
            placement="right"
            :show-after="200"
            effect="light"
            popper-class="tm-cfg-tooltip"
          >
            <template #content>
              <pre class="tm-cfg-json">{{ cfgJson(row.id) }}</pre>
            </template>
            <span class="id-cell">{{ row.id }}</span>
          </el-tooltip>
          <span v-else>{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="参数名称" min-width="180" show-overflow-tooltip />
      <el-table-column label="当前值" width="160">
        <template #default="{ row }">
          <span
            :class="cellClass(row.id)"
            class="value-cell"
            @click="goCurve(row)"
          >{{ row.show ?? row.value }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="unit" label="单位" width="80" />
      <el-table-column prop="hex" label="HEX" min-width="120" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup name="PayloadTelemetryTable">
import { useRoute, useRouter } from 'vue-router'
import { getTelemetryTable } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'

const route = useRoute()
const router = useRouter()
const ACTIVE_KEY = 'payload:activeDeviceId'

/** 优先从路径 tmFF 解析类型，兼容旧链接 ?type=FF */
function resolveTmType(r = route) {
  const fromQuery = r.query?.type
  if (fromQuery) return String(fromQuery).toUpperCase()
  const seg = (r.path || '').split('/').filter(Boolean).pop() || ''
  if (/^tm[0-9A-Fa-f]{2}$/i.test(seg)) return seg.slice(2).toUpperCase()
  return 'FF'
}

const tmType = computed(() => resolveTmType())
const tableName = ref('')
const defRows = ref([])
const defById = ref({})
const rows = ref([])
const prevValues = ref({})
const changedIds = ref(new Set())
const initialLoading = ref(false)
const connected = ref(false)
const dataTs = ref('')
const refreshTs = ref('')
const dataId = ref('')
const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
let pollTimer = null

function formatNow() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function isEmptyVal(v) {
  return v === undefined || v === null || String(v).trim() === ''
}

function cellClass(id) {
  return changedIds.value.has(id) ? 'cell-changed' : ''
}

function goCurve(row) {
  router.push({ path: '/telemetry/curve', query: { type: tmType.value, field: row.id, from: 'table' } })
}

function cfgJson(id) {
  const cfg = defById.value[id]
  return cfg ? JSON.stringify(cfg, null, 2) : ''
}

function hasLocalCfg() {
  return Object.keys(defById.value).length > 0
}

/** 无实时数据时，用配置表字段占位：编号/名称/单位有值，当前值与 HEX 为空 */
function skeletonFromDef(data) {
  return (data?.row || [])
    .filter(r => r.id)
    .map(r => ({
      id: r.id || '',
      name: r.name || '',
      value: '',
      show: '',
      unit: r.unit || '',
      hex: ''
    }))
}

function applyCfg(cfg) {
  if (!cfg) return
  if (cfg.name) tableName.value = cfg.name
  const map = {}
  for (const r of cfg.row || []) {
    if (r.id) map[r.id] = r
  }
  defById.value = map
  defRows.value = skeletonFromDef(cfg)
}

function applyRows(next) {
  const display = next.length ? next : defRows.value.map(r => ({ ...r }))
  const changed = new Set()
  display.forEach(r => {
    const key = r.id
    const val = String(r.show ?? r.value ?? '')
    const prev = prevValues.value[key]
    // 仅当原值非空且与新值不同时标红；空→有数据不标红
    if (prev !== undefined && !isEmptyVal(prev) && prev !== val) {
      changed.add(key)
    }
    prevValues.value[key] = val
  })
  changedIds.value = changed
  // 就地更新已有行，减少整表重绘闪烁
  if (rows.value.length === display.length && rows.value.length) {
    const byId = new Map(display.map(r => [r.id, r]))
    let sameOrder = true
    for (let i = 0; i < rows.value.length; i++) {
      const id = rows.value[i].id
      const n = byId.get(id)
      if (!n || display[i]?.id !== id) {
        sameOrder = false
        break
      }
      rows.value[i].name = n.name
      rows.value[i].value = n.value
      rows.value[i].show = n.show
      rows.value[i].unit = n.unit
      rows.value[i].hex = n.hex
    }
    if (!sameOrder) rows.value = display
  } else {
    rows.value = display
  }
}

async function refresh({ showLoading = false, needCfg = false } = {}) {
  if (showLoading) initialLoading.value = true
  try {
    const res = await getTelemetryTable(deviceId.value, tmType.value, dataId.value, needCfg)
    refreshTs.value = formatNow()
    const data = res.data || {}
    if (data.cfg) applyCfg(data.cfg)
    if (data.name) tableName.value = data.name
    dataTs.value = data.ts || ''
    connected.value = !!data.connected
    dataId.value = data.dataId ?? ''

    // 快照未变：只更新刷新时间，不碰表格
    if (!data.changed) return

    applyRows(data.rows || [])
  } finally {
    if (showLoading) initialLoading.value = false
  }
}

async function loadDevices() {
  const res = await listCanChannels()
  const list = (res.data || []).map(d => d.deviceId).filter(Boolean)
  if (list.length) deviceOptions.value = list
}

function onDeviceChange() {
  localStorage.setItem(ACTIVE_KEY, deviceId.value)
  prevValues.value = {}
  dataId.value = ''
  refresh({ showLoading: true, needCfg: !hasLocalCfg() })
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(() => refresh({ showLoading: false, needCfg: false }), 1000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function resetForType() {
  prevValues.value = {}
  changedIds.value = new Set()
  rows.value = []
  defRows.value = []
  defById.value = {}
  tableName.value = ''
  dataTs.value = ''
  dataId.value = ''
  await refresh({ showLoading: true, needCfg: true })
}

onMounted(async () => {
  initialLoading.value = true
  try {
    await Promise.all([
      refresh({ showLoading: false, needCfg: true }),
      loadDevices()
    ])
  } finally {
    initialLoading.value = false
  }
  startPoll()
})

watch(
  () => route.path,
  async (path, oldPath) => {
    if (path === oldPath) return
    const seg = (path || '').split('/').filter(Boolean).pop() || ''
    if (!/^tm[0-9A-Fa-f]{2}$/i.test(seg)) return
    await resetForType()
  }
)

onUnmounted(stopPoll)
</script>

<style scoped>
.tm-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.tm-ts {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.value-cell { cursor: pointer; }
.id-cell { cursor: help; }
.cell-changed { color: #f56c6c; }
</style>

<!-- tooltip 挂到 body，需非 scoped；用 EP light + CSS 变量适配明暗主题 -->
<style>
.tm-cfg-tooltip.el-popper {
  max-width: min(480px, 90vw) !important;
  /* 沿用 Element Plus light popper：bg=--el-bg-color-overlay，随 html.dark 切换 */
  color: var(--el-text-color-primary);
}
.tm-cfg-tooltip .tm-cfg-json {
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre;
  color: inherit;
  font-family: var(--el-font-family-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.45;
}
</style>
