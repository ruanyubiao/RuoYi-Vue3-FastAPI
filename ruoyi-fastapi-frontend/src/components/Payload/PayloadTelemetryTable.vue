<template>
  <div class="payload-tm-table" :class="levelClass">
    <div class="tm-header">
      <div class="tm-head-left">
        <el-select
          v-if="isMultiType"
          :model-value="normalizedType"
          :size="preset.controlSize"
          class="tm-key-select"
          @update:model-value="onTypeSelect"
        >
          <el-option
            v-for="o in typeList"
            :key="o.id"
            :label="o.label"
            :value="o.id"
          />
        </el-select>
        <span v-else class="tm-title">{{ currentLabel }}</span>
      </div>
      <el-tag :size="preset.controlSize" :type="dataSource ? 'success' : 'info'">
        {{ dataSource || '无数据' }}
      </el-tag>
      <span class="tm-ts">刷新时间: {{ refreshTs || '-' }}</span>
      <span class="tm-ts">数据时间: {{ dataTs || '-' }}</span>
    </div>
    <div class="tm-table-wrap">
      <el-table
        :data="rows"
        v-loading="initialLoading"
        row-key="id"
        border
        stripe
        height="100%"
        :size="preset.tableSize"
        empty-text="暂无数据"
      >
        <el-table-column label="编号" :width="preset.idWidth">
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
        <el-table-column
          prop="name"
          label="参数名称"
          :width="preset.nameWidth"
          :min-width="preset.nameMinWidth"
          show-overflow-tooltip
        />
        <el-table-column label="当前值" :width="preset.valueWidth">
          <template #default="{ row }">
            <span
              :class="cellClass(row.id)"
              class="value-cell"
              :title="enableCurveNav ? '双击查看曲线' : undefined"
              @dblclick="onValueDblClick(row)"
            >{{ row.show ?? row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" :width="preset.unitWidth" />
        <el-table-column
          prop="hex"
          label="HEX"
          :min-width="preset.hexMinWidth"
          show-overflow-tooltip
        />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { getTelemetryTable } from '@/api/payload/telemetry'
import { takeTelemetryCfg, saveTelemetryCfg, tmTypeCfgScope } from '@/utils/telemetryCfgCache'

/** 头部/表格尺寸档位：t1 整页 → t3 小区域，样式与列宽集中在此，避免分支判断 */
const LEVEL_PRESETS = {
  t1: {
    controlSize: 'default',
    tableSize: 'default',
    idWidth: 80,
    nameWidth: 320,
    nameMinWidth: undefined,
    valueWidth: 180,
    unitWidth: 80,
    hexMinWidth: 120
  },
  t2: {
    controlSize: 'small',
    tableSize: 'small',
    idWidth: 88,
    nameWidth: undefined,
    nameMinWidth: 180,
    valueWidth: 140,
    unitWidth: 72,
    hexMinWidth: 100
  },
  t3: {
    controlSize: 'small',
    tableSize: 'small',
    idWidth: 88,
    nameWidth: undefined,
    nameMinWidth: 140,
    valueWidth: 120,
    unitWidth: 64,
    hexMinWidth: 90
  }
}

const props = defineProps({
  /**
   * 遥测表类型列表，统一用数组传入：
   * - 1 项 → 头部显示标题
   * - 多项 → 头部显示下拉
   * 元素可为 'FF' 或 { id: 'D8', name: '慢遥测(全窗)' }
   */
  types: { type: Array, required: true },
  /** 当前选中类型；多项时配合 v-model:type 使用，未传则取第一项 */
  type: { type: String, default: '' },
  /** 头部/表格档位：t1 整页、t2 中等、t3 小区域 */
  level: {
    type: String,
    default: 't1',
    validator: v => ['t1', 't2', 't3'].includes(v)
  },
  pollMs: { type: Number, default: 1000 },
  enableCurveNav: { type: Boolean, default: true }
})

const emit = defineEmits(['update:type', 'data-change'])

const router = useRouter()

function normalizeOption(o) {
  const id = String((typeof o === 'string' ? o : o?.id || o?.key) || '')
    .trim()
    .toUpperCase()
  const name = typeof o === 'string' ? '' : o?.name || ''
  const localKey =
    typeof o === 'string' ? '' : String(o?.localKey || o?.local_key || '').trim()
  const customLabel = typeof o === 'string' ? '' : String(o?.label || '').trim()
  const displayId = localKey || id
  return {
    id,
    name,
    label: customLabel || (name ? `${displayId}：${name}` : displayId)
  }
}

const typeList = computed(() => (props.types || []).map(normalizeOption).filter(o => o.id))
const isMultiType = computed(() => typeList.value.length > 1)

const normalizedType = computed(() => {
  const explicit = String(props.type || '').trim().toUpperCase()
  if (explicit && typeList.value.some(o => o.id === explicit)) return explicit
  return typeList.value[0]?.id || explicit
})

const preset = computed(() => LEVEL_PRESETS[props.level] || LEVEL_PRESETS.t1)
const levelClass = computed(() => `level-${props.level}`)

const tableName = ref('')
const defRows = ref([])
const defById = ref({})
const rows = ref([])
const prevValues = ref({})
const changedIds = ref(new Set())
const initialLoading = ref(false)
const dataSource = ref('')
const dataTs = ref('')
const refreshTs = ref('')
const dataId = ref('')
let pollTimer = null
let refreshing = false

/** 单类型时的标题：优先配置表名，其次列表里配的名称，最后类型本身 */
const currentLabel = computed(() => {
  if (tableName.value) return tableName.value
  const hit = typeList.value.find(o => o.id === normalizedType.value)
  return hit?.name || hit?.id || normalizedType.value
})

function cfgScope(type = normalizedType.value) {
  return tmTypeCfgScope(type)
}

function onTypeSelect(v) {
  const next = String(v || '').toUpperCase()
  if (next && next !== normalizedType.value) {
    emit('update:type', next)
  }
}

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

function cfgJson(id) {
  const cfg = defById.value[id]
  return cfg ? JSON.stringify(cfg, null, 2) : ''
}

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
  if (cfg.row?.length) {
    saveTelemetryCfg(cfgScope(), {
      name: cfg.name || tableName.value,
      tableKey: normalizedType.value,
      cfgRows: cfg.row,
      cfgName: cfg.name || ''
    })
  }
}

function applyCachedCfg() {
  const cached = takeTelemetryCfg(cfgScope())
  if (!cached?.cfgRows?.length) return false
  applyCfg({
    name: cached.cfgName || cached.name || '',
    row: cached.cfgRows
  })
  if (!rows.value.length) {
    rows.value = defRows.value.map(r => ({ ...r }))
  }
  return true
}

function applyRows(next) {
  const display = next.length ? next : defRows.value.map(r => ({ ...r }))
  const changed = new Set()
  display.forEach(r => {
    const key = r.id
    const val = String(r.show ?? r.value ?? '')
    const prev = prevValues.value[key]
    if (prev !== undefined && !isEmptyVal(prev) && prev !== val) {
      changed.add(key)
    }
    prevValues.value[key] = val
  })
  changedIds.value = changed
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

function emitDataChange() {
  emit('data-change', {
    type: normalizedType.value,
    rows: rows.value,
    ts: dataTs.value,
    dataId: dataId.value,
    dataSource: dataSource.value,
    name: tableName.value
  })
}

async function refresh({ showLoading = false, needCfg = false } = {}) {
  if (refreshing || !normalizedType.value) return
  refreshing = true
  if (showLoading) initialLoading.value = true
  try {
    const res = await getTelemetryTable(normalizedType.value, dataId.value, needCfg)
    refreshTs.value = formatNow()
    const data = res.data || {}
    if (data.cfg) applyCfg(data.cfg)
    if (data.name) tableName.value = data.name
    dataTs.value = data.ts || ''
    dataSource.value = data.dataSource || data.srcParam || ''
    dataId.value = data.dataId ?? ''

    if (!data.changed) {
      emitDataChange()
      return
    }

    applyRows(data.rows || [])
    emitDataChange()
  } catch {
    if (!defRows.value.length) applyCachedCfg()
    if (!rows.value.length && defRows.value.length) {
      rows.value = defRows.value.map(r => ({ ...r }))
    }
    emitDataChange()
  } finally {
    refreshing = false
    if (showLoading) initialLoading.value = false
  }
}

function startPoll() {
  stopPoll()
  const ms = Math.max(200, Number(props.pollMs) || 1000)
  pollTimer = setInterval(() => refresh({ showLoading: false, needCfg: false }), ms)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function resetForType() {
  stopPoll()
  prevValues.value = {}
  changedIds.value = new Set()
  rows.value = []
  defRows.value = []
  defById.value = {}
  tableName.value = ''
  dataTs.value = ''
  dataId.value = ''
  dataSource.value = ''
  applyCachedCfg()
  await refresh({ showLoading: true, needCfg: true })
  startPoll()
}

function onValueDblClick(row) {
  if (!props.enableCurveNav || !row?.id) return
  // type 已是存储键 BIU:FF / XL:FF，无需再传 family
  router.push({
    path: '/telemetry/curve',
    query: {
      type: normalizedType.value,
      field: row.id,
      from: 'table'
    }
  })
}

watch(
  () => normalizedType.value,
  async (t, old) => {
    if (!t || t === old) return
    await resetForType()
  }
)

watch(
  () => props.pollMs,
  () => {
    if (pollTimer) startPoll()
  }
)

onMounted(async () => {
  applyCachedCfg()
  initialLoading.value = true
  try {
    await refresh({ showLoading: false, needCfg: true })
  } finally {
    initialLoading.value = false
  }
  startPoll()
})

onUnmounted(stopPoll)

defineExpose({ refresh, resetForType })
</script>

<style scoped>
.payload-tm-table {
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.tm-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.tm-head-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.tm-title {
  margin: 0;
  font-weight: 600;
  line-height: 1.3;
}
.tm-table-wrap {
  flex: 1;
  min-height: 0;
}
.tm-ts {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
.value-cell {
  user-select: none;
}
.value-cell[title] {
  cursor: pointer;
}
.id-cell {
  cursor: help;
}
.cell-changed {
  color: #f56c6c;
}

/* t1：整页，上下留白充足 */
.level-t1 .tm-header {
  margin-bottom: 12px;
  padding: 4px 0;
}
.level-t1 .tm-title {
  font-size: 16px;
}
.level-t1 .tm-ts {
  margin-left: 8px;
  font-size: 13px;
}
.level-t1 .tm-key-select {
  width: 220px;
}

/* t2：中等区域 */
.level-t2 .tm-header {
  margin-bottom: 8px;
  padding: 2px 0;
  gap: 8px;
}
.level-t2 .tm-title {
  font-size: 14px;
}
.level-t2 .tm-ts {
  font-size: 12px;
}
.level-t2 .tm-key-select {
  width: 180px;
}

/* t3：小区域，几乎无上下 padding */
.level-t3 .tm-header {
  margin-bottom: 4px;
  padding: 0;
  gap: 6px;
}
.level-t3 .tm-title {
  font-size: 13px;
}
.level-t3 .tm-ts {
  font-size: 12px;
}
.level-t3 .tm-key-select {
  width: 168px;
}
</style>

<style>
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
