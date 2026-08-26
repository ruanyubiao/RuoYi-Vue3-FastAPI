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
import { getTelemetryTableBatch } from '@/api/payload/telemetry'
import { takeTelemetryCfg, saveTelemetryCfg, tmTypeCfgScope, isTelemetryCfgStale } from '@/utils/telemetryCfgCache'

/** 头部/表格尺寸档位：t1 整页 → t3 小区域 */
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
  level: {
    type: String,
    default: 't1',
    validator: v => ['t1', 't2', 't3'].includes(v)
  },
  pollMs: { type: Number, default: 1000 },
  enableCurveNav: { type: Boolean, default: true },
  /** 有效数据类型变化时才自动切换下拉（默认关；相机开） */
  autoSwitchType: { type: Boolean, default: false }
})

const emit = defineEmits(['update:type', 'data-change', 'snaps-change'])

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
const typeIds = computed(() => typeList.value.map(o => o.id))

const normalizedType = computed(() => {
  const explicit = String(props.type || '').trim().toUpperCase()
  if (explicit && typeList.value.some(o => o.id === explicit)) return explicit
  return typeList.value[0]?.id || explicit
})

const preset = computed(() => LEVEL_PRESETS[props.level] || LEVEL_PRESETS.t1)
const levelClass = computed(() => `level-${props.level}`)

/** 多表缓存：type -> snap（cfg + 最新 rows/ts/dataId，切表不丢） */
const snapByType = reactive({})
/** 上次自动切到的有效类型；相同则不重复 emit，避免下拉抖动 */
const lastEffectiveType = ref('')

/** 当前展示表名（来自 cfg.name） */
const tableName = ref('')
/** 配置骨架行（无值时的空表） */
const defRows = ref([])
const defById = ref({})
/** 当前下拉对应表的展示行 */
const rows = ref([])
/** 上一轮值，用于变红高亮 */
const prevValues = ref({})
const changedIds = ref(new Set())
const initialLoading = ref(false)
const dataSource = ref('')
const dataTs = ref('')
const refreshTs = ref('')
const dataId = ref('')
let pollTimer = null
let refreshing = false
/** 各表是否已请求过 cfg */
const cfgLoaded = reactive({})

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

function rowsHaveValues(rowList) {
  return (rowList || []).some(r => {
    const s = r?.show ?? r?.value
    return s !== '' && s != null && String(s).trim() !== ''
  })
}

function parseDataTsMs(ts) {
  if (!ts) return 0
  const t = Date.parse(String(ts).trim().replace(/-/g, '/'))
  return Number.isFinite(t) ? t : 0
}

/** 取或创建某 type 的 snap 槽（切表后仍保留各表最新数据） */
function ensureSnap(type) {
  const key = String(type || '').toUpperCase()
  if (!key) return null
  if (!snapByType[key]) {
    snapByType[key] = {
      type: key,
      rows: [],
      ts: '',
      dataId: '',
      name: '',
      dataSource: '',
      cfg: null,
      cfgDatetime: '',
      cfgMtime: ''
    }
  }
  return snapByType[key]
}

/** 写入该 type 的 cfg 到 snap；若是当前展示表则立刻套到表格 */
function applyCfgToType(type, cfg, meta = {}) {
  if (!cfg) return
  const snap = ensureSnap(type)
  snap.cfg = cfg
  if (cfg.name) snap.name = cfg.name
  if (meta.cfgDatetime != null) snap.cfgDatetime = meta.cfgDatetime
  if (meta.cfgMtime != null) snap.cfgMtime = meta.cfgMtime
  if (cfg.row?.length) {
    saveTelemetryCfg(cfgScope(type), {
      name: cfg.name || snap.name,
      tableKey: type,
      cfgRows: cfg.row,
      cfgName: cfg.name || '',
      cfgDatetime: meta.cfgDatetime || snap.cfgDatetime || '',
      cfgMtime: meta.cfgMtime || snap.cfgMtime || ''
    })
  }
  if (type === normalizedType.value) {
    applyCfgLocal(cfg)
  }
}

function applyCfgLocal(cfg) {
  if (!cfg) return
  if (cfg.name) tableName.value = cfg.name
  const map = {}
  for (const r of cfg.row || []) {
    if (r.id) map[r.id] = r
  }
  defById.value = map
  defRows.value = skeletonFromDef(cfg)
}

function applyCachedCfgForType(type) {
  const cached = takeTelemetryCfg(cfgScope(type))
  if (!cached?.cfgRows?.length) return false
  const cfg = { name: cached.cfgName || cached.name || '', row: cached.cfgRows }
  applyCfgToType(type, cfg)
  const snap = ensureSnap(type)
  if (!snap.rows.length) {
    snap.rows = skeletonFromDef(cfg)
  }
  return true
}

function mergeRowsForDisplay(next, skeleton) {
  // 有配置骨架时：行序/名称/单位以 cfg 为准，值按 id 从 Redis 行叠上（避免旧解析字段盖住新配置）
  if (skeleton?.length) {
    const byId = new Map((next || []).map(r => [String(r?.id || ''), r]))
    return skeleton.map(s => {
      const v = byId.get(String(s.id || ''))
      return {
        id: s.id || '',
        name: s.name || '',
        unit: s.unit || '',
        value: v?.value ?? '',
        show: v?.show ?? v?.value ?? '',
        hex: v?.hex ?? ''
      }
    })
  }
  return next?.length ? next : []
}

/** 叠值到当前表格行，并标出相对上一轮变化的 id */
function applyRowsLocal(next) {
  const display = mergeRowsForDisplay(next, defRows.value)
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

/** 用当前 type 的 snap 刷新表格展示（切表/轮询后；不重新请求） */
function paintActiveFromSnap() {
  const type = normalizedType.value
  const snap = ensureSnap(type)
  if (snap.cfg) applyCfgLocal(snap.cfg)
  else applyCachedCfgForType(type)
  tableName.value = snap.name || tableName.value
  dataTs.value = snap.ts || ''
  dataId.value = snap.dataId ?? ''
  dataSource.value = snap.dataSource || ''
  applyRowsLocal(snap.rows || [])
}

function emitDataChange() {
  emit('data-change', {
    type: normalizedType.value,
    rows: rows.value,
    ts: dataTs.value,
    dataId: dataId.value,
    dataSource: dataSource.value,
    name: tableName.value,
    snaps: getAllSnaps()
  })
}

function emitSnapsChange() {
  emit('snaps-change', getAllSnaps())
}

/** 将 batch 单项写入对应表 snap（cfg / rows / ts / dataId） */
function ingestItem(item, { needCfgHint = false } = {}) {
  const type = String(item?.type || '').toUpperCase()
  if (!type) return
  const snap = ensureSnap(type)
  if (item.cfgDatetime != null) snap.cfgDatetime = item.cfgDatetime
  if (item.cfgMtime != null) snap.cfgMtime = item.cfgMtime
  if (item.cfg) {
    applyCfgToType(type, item.cfg, {
      cfgDatetime: item.cfgDatetime || snap.cfgDatetime || '',
      cfgMtime: item.cfgMtime || snap.cfgMtime || ''
    })
    cfgLoaded[type] = true
  } else if (
    isTelemetryCfgStale(cfgScope(type), {
      cfgDatetime: item.cfgDatetime,
      cfgMtime: item.cfgMtime
    })
  ) {
    cfgLoaded[type] = false
  }
  if (item.name) snap.name = item.name
  if (item.ts) snap.ts = String(item.ts)
  if (item.dataId != null && item.dataId !== '') snap.dataId = item.dataId
  if (item.dataSource != null || item.srcParam != null) {
    snap.dataSource = item.dataSource || item.srcParam || ''
  }
  if (item.changed !== false && Array.isArray(item.rows)) {
    snap.rows = item.rows
  } else if (!snap.rows.length && item.cfg) {
    snap.rows = skeletonFromDef(item.cfg)
  } else if (!snap.rows.length && needCfgHint) {
    applyCachedCfgForType(type)
  }
}

/** snap 是否有真实遥测（有 ts/dataId 且行有值） */
function snapHasValidData(type) {
  const snap = snapByType[String(type || '').toUpperCase()]
  if (!snap) return false
  const hasReal = !!(snap.ts || (snap.dataId != null && snap.dataId !== '' && Number(snap.dataId) !== 0))
  return hasReal && rowsHaveValues(snap.rows)
}

/**
 * 有效数据类型：多表都有值时取数据时间最新的；无有效数据返回空。
 * 与 getActiveType（当前下拉选中）不同，可与下拉不一致。
 */
function computeEffectiveType() {
  const ids = typeIds.value
  const ok = ids.filter(id => snapHasValidData(id))
  if (!ok.length) return ''
  if (ok.length === 1) return ok[0]
  let best = ok[0]
  let bestTs = parseDataTsMs(snapByType[best]?.ts)
  for (let i = 1; i < ok.length; i++) {
    const id = ok[i]
    const ts = parseDataTsMs(snapByType[id]?.ts)
    if (ts >= bestTs) {
      best = id
      bestTs = ts
    }
  }
  return best
}

/** 有效类型变化时才切下拉（autoSwitchType）；同一有效类型不重复 emit */
function maybeAutoSwitch() {
  if (!props.autoSwitchType) return
  const next = computeEffectiveType()
  if (!next) return
  // 有效类型未变（例如仍是 D8）→ 不切下拉
  if (next === lastEffectiveType.value) return
  lastEffectiveType.value = next
  if (normalizedType.value !== next) {
    emit('update:type', next)
  }
}

async function refreshBatch({ showLoading = false, needCfg = false } = {}) {
  const ids = typeIds.value
  if (refreshing || !ids.length) return
  refreshing = true
  if (showLoading) initialLoading.value = true
  try {
    const items = ids.map(type => {
      const snap = ensureSnap(type)
      const stale = isTelemetryCfgStale(cfgScope(type), {
        cfgDatetime: snap.cfgDatetime,
        cfgMtime: snap.cfgMtime
      })
      const wantCfg = needCfg || !cfgLoaded[type] || stale
      const did = snap.dataId != null && snap.dataId !== '' ? String(snap.dataId) : undefined
      return {
        type,
        dataId: did || undefined,
        needCfg: wantCfg
      }
    })
    const res = await getTelemetryTableBatch(items)
    refreshTs.value = formatNow()
    const rowsUpdatedTypes = new Set()
    const cfgUpdatedTypes = new Set()
    let needCfgAgain = false
    for (const item of res.data?.items || []) {
      const t = String(item?.type || '').toUpperCase()
      const rowsUpdated = item?.changed !== false && Array.isArray(item.rows)
      ingestItem(item, { needCfgHint: needCfg })
      if (t && rowsUpdated) rowsUpdatedTypes.add(t)
      if (t && item.cfg) cfgUpdatedTypes.add(t)
      if (t && (needCfg || item.cfg)) cfgLoaded[t] = true
      // 仅带回时间戳、配置已过期且本轮未带 cfg → 再拉一轮
      if (
        t &&
        !item.cfg &&
        isTelemetryCfgStale(cfgScope(t), {
          cfgDatetime: item.cfgDatetime,
          cfgMtime: item.cfgMtime
        })
      ) {
        cfgLoaded[t] = false
        needCfgAgain = true
      }
    }
    const activeBefore = normalizedType.value
    maybeAutoSwitch()
    // 无新数据（dataId/时间未变）不重绘表格，保留变红高亮；有新行或切表/拉 cfg 再刷
    const activeAfter = normalizedType.value
    if (
      needCfg ||
      showLoading ||
      activeAfter !== activeBefore ||
      rowsUpdatedTypes.has(activeAfter) ||
      cfgUpdatedTypes.has(activeAfter)
    ) {
      paintActiveFromSnap()
    }
    emitDataChange()
    emitSnapsChange()
    if (needCfgAgain && !needCfg) {
      refreshing = false
      await refreshBatch({ showLoading: false, needCfg: true })
      return
    }
  } catch {
    for (const id of ids) applyCachedCfgForType(id)
    paintActiveFromSnap()
    emitDataChange()
    emitSnapsChange()
  } finally {
    refreshing = false
    if (showLoading) initialLoading.value = false
  }
}

function startPoll() {
  stopPoll()
  const ms = Number(props.pollMs)
  if (!ms || ms <= 0) return
  pollTimer = setInterval(() => refreshBatch({ showLoading: false, needCfg: false }), Math.max(200, ms))
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 切表：清空变红高亮，从该表 snap 重绘（不重新请求） */
function switchActiveTypeView() {
  prevValues.value = {}
  changedIds.value = new Set()
  paintActiveFromSnap()
  emitDataChange()
}

function onValueDblClick(row) {
  if (!props.enableCurveNav || !row?.id) return
  router.push({
    path: '/telemetry/curve',
    query: {
      type: normalizedType.value,
      field: row.id,
      from: 'table'
    }
  })
}

/** —— 对外读缓存 API —— */
function getAllSnaps() {
  const out = {}
  for (const id of typeIds.value) {
    const s = snapByType[id]
    if (!s) continue
    out[id] = {
      type: id,
      rows: Array.isArray(s.rows) ? s.rows.map(r => ({ ...r })) : [],
      ts: s.ts || '',
      dataId: s.dataId ?? '',
      name: s.name || '',
      dataSource: s.dataSource || ''
    }
  }
  return out
}

function getTable(type) {
  const key = String(type || normalizedType.value || '').toUpperCase()
  const s = snapByType[key]
  if (!s) return null
  return {
    type: key,
    rows: Array.isArray(s.rows) ? s.rows.map(r => ({ ...r })) : [],
    ts: s.ts || '',
    dataId: s.dataId ?? '',
    name: s.name || '',
    dataSource: s.dataSource || ''
  }
}

function getField(type, fieldId) {
  const table = getTable(type)
  if (!table || !fieldId) return null
  const id = String(fieldId).toUpperCase()
  const row = (table.rows || []).find(r => String(r?.id || '').toUpperCase() === id)
  return row ? { ...row } : null
}

function getFields(type, fieldIds) {
  const ids = (fieldIds || []).map(x => String(x).toUpperCase())
  const table = getTable(type)
  if (!table) return []
  const byId = new Map((table.rows || []).map(r => [String(r?.id || '').toUpperCase(), r]))
  return ids.map(id => (byId.has(id) ? { ...byId.get(id) } : null)).filter(Boolean)
}

/** 当前下拉选中的表类型（用户选择或 autoSwitch 写入） */
function getActiveType() {
  return normalizedType.value || ''
}

/** 缓存中数据最新且有有效值的表类型（可与下拉不一致；相机统计区/分辨率跟这个） */
function getEffectiveType() {
  return computeEffectiveType()
}

watch(
  () => normalizedType.value,
  (t, old) => {
    if (!t || t === old) return
    switchActiveTypeView()
  }
)

watch(
  () => props.pollMs,
  () => {
    if (pollTimer) startPoll()
  }
)

watch(
  typeIds,
  (ids, oldIds) => {
    const a = (ids || []).join('|')
    const b = (oldIds || []).join('|')
    if (a === b) return
    // types 列表变了：重置自动切表记忆，重新拉 cfg
    lastEffectiveType.value = ''
    refreshBatch({ showLoading: true, needCfg: true })
  }
)

onMounted(async () => {
  for (const id of typeIds.value) applyCachedCfgForType(id)
  paintActiveFromSnap()
  initialLoading.value = true
  try {
    await refreshBatch({ showLoading: false, needCfg: true })
  } finally {
    initialLoading.value = false
  }
  startPoll()
})

/** keep-alive 切走不会 unmount，必须在 deactivated 停轮询，否则多页同时 batch */
onActivated(() => {
  startPoll()
})

onDeactivated(() => {
  stopPoll()
})

onUnmounted(stopPoll)

defineExpose({
  refresh: () => refreshBatch({ showLoading: false, needCfg: false }),
  refreshBatch,
  getAllSnaps,
  getTable,
  getField,
  getFields,
  getActiveType,
  getEffectiveType
})
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
