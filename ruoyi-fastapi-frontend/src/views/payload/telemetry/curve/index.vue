<template>
  <div class="app-container curve-page">
    <div class="toolbar-row">
      <el-form :inline="true" class="toolbar">
        <el-form-item label="设备">
          <el-select v-model="deviceId" style="width: 200px">
            <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="遥测表">
          <el-select v-model="tmType" style="width: 160px" @change="onTypeChange">
            <el-option v-for="p in tmPages" :key="p.key" :label="p.name" :value="p.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="遥测量">
          <el-select v-model="field" filterable style="width: 220px">
            <el-option v-for="f in fields" :key="f.id" :label="`${f.id} ${f.name}`" :value="f.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            :type="isCurrentOnChart ? 'danger' : 'primary'"
            class="action-btn"
            :loading="adding"
            :disabled="curveActionDisabled"
            @click="onCurveAction"
          >
            {{ isCurrentOnChart ? '删除曲线' : '增加曲线' }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="icon-tool-group">
        <el-tooltip :content="cropMode ? '再次点击取消截取' : '截取时间片段（拖选）'" placement="top">
          <span class="icon-tool-wrap">
            <el-button
              class="icon-tool-btn"
              :type="cropMode ? 'primary' : 'default'"
              :disabled="!curves.length"
              @click="onToggleCrop"
            >
              <el-icon><Crop /></el-icon>
            </el-button>
          </span>
        </el-tooltip>
        <el-tooltip content="导出当前时间窗口数据为 CSV" placement="top">
          <span class="icon-tool-wrap">
            <el-button class="icon-tool-btn" :disabled="!curves.length" @click="exportCurveCsv">
              <el-icon><Download /></el-icon>
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <el-form :inline="true" class="toolbar-options">
      <el-form-item label="起始时间">
        <el-date-picker
          v-model="queryStartAt"
          type="datetime"
          placeholder="选择起始时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          format="YYYY-MM-DD HH:mm:ss"
          :clearable="false"
          style="width: 200px"
        />
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          class="action-btn"
          :disabled="!curves.length"
          :loading="querying"
          @click="queryFromStartTime"
        >
          查询
        </el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置</el-button>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="zoomX">X轴缩放</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="zoomY">Y轴缩放</el-checkbox>
      </el-form-item>
    </el-form>

    <div v-if="curves.length" class="curve-legend">
      <div v-for="c in curves" :key="c.key" class="legend-item">
        <span class="legend-dot" :style="{ background: c.color }" />
        <span class="legend-label">{{ c.field }} {{ c.name }}{{ c.unit ? ` (${c.unit})` : '' }}</span>
        <el-button class="legend-remove" circle size="small" @click="removeCurve(c.key)">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="chart-wrap">
      <div v-if="!curves.length" class="empty-hint">请选择遥测量后点击「增加曲线」</div>
      <div ref="chartRef" class="chart-box" />
    </div>
  </div>
</template>

<script setup name="Curve">
import { Close, Crop, Download } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTelemetryConfig } from '@/api/payload/config'
import { getTelemetryCurveDataBatch, getTelemetryFields } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'
import { useTimeSeriesChart } from '@/components/TimeSeriesChart'
import { buildAlignedSeriesTable, exportCsvFile, formatCsvDateTime } from '@/utils/csvExport'

const CURVE_FETCH_LIMIT = 50000
const CURVE_INCREMENT_LIMIT = 500
const CURVE_DISPLAY_MAX = 50000
const CURVE_PAUSE_CACHE_MAX = 1000
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000
const POLL_INTERVAL_MS = 1000
const MAX_CURVES = 10

const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]

const route = useRoute()
const ACTIVE_KEY = 'payload:activeDeviceId'
const chartRef = ref(null)
let pollTimer = null
let tickBusy = false
const keyColorIdx = {}
const activeColorIndices = new Set()
const globalClearedAt = ref(null)

const tmPages = ref([])
const tmType = ref((route.query.type || 'FF').toString().toUpperCase())
const field = ref(route.query.field ? String(route.query.field) : '')
const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
const fields = ref([])
const curves = ref([])
const adding = ref(false)
const autoRefresh = ref(true)
const zoomX = ref(true)
const zoomY = ref(true)
/** 查询起始时间：YYYY-MM-DD HH:mm:ss，初始对齐底部时间轴起点 */
const queryStartAt = ref('')
const querying = ref(false)

function formatDateTimeSec(ms) {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function parseQueryStartMs() {
  const s = queryStartAt.value
  if (!s) return NaN
  // 兼容 "YYYY-MM-DD HH:mm:ss"
  const t = Date.parse(String(s).replace(/-/g, '/'))
  return t
}

/** 用底部 dataZoom 起始时间刷新查询框（无有效窗口时用最早点或当前时间） */
function syncQueryStartFromChart({ force = false } = {}) {
  if (!force && queryStartAt.value) return
  const win = tsChart.getTimeWindow()
  let start = win?.start
  if (start == null || !Number.isFinite(Number(start)) || Number(start) <= 0) {
    start = tsChart.getEarliestTime() || Date.now()
  }
  start = Number(start)
  // 过滤异常时间（例如解析错误导致的历史年）
  if (!Number.isFinite(start) || start < 946684800000) {
    // < 2000-01-01
    start = Date.now()
  }
  queryStartAt.value = formatDateTimeSec(start)
}

function curveKey(dev, type, fld) {
  return `${dev}:${type}:${fld}`
}

const currentCurveKey = computed(() => {
  if (!field.value || !deviceId.value) return ''
  return curveKey(deviceId.value, tmType.value, field.value)
})

const isCurrentOnChart = computed(() => {
  if (!currentCurveKey.value) return false
  return curves.value.some(c => c.key === currentCurveKey.value)
})

const curveActionDisabled = computed(() => !field.value || !deviceId.value || adding.value)

const tsChart = useTimeSeriesChart({
  chartRef,
  zoomX,
  zoomY,
  defaultViewWindowMs: DEFAULT_VIEW_WINDOW_MS,
  getSeries: () =>
    curves.value.map(c => ({
      id: c.key,
      name: `${c.field} ${c.name}`,
      type: 'line',
      showSymbol: false,
      data: c.points,
      itemStyle: { color: c.color },
      lineStyle: { color: c.color }
    })),
  getSeriesPoints: () => curves.value
})

const cropMode = tsChart.cropMode

function onResetTimeWindow() {
  tsChart.resetTimeWindow()
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

function acquireColor(key) {
  if (keyColorIdx[key] === undefined) {
    let idx = 0
    while (activeColorIndices.has(idx)) idx++
    if (idx >= MAX_CURVES) return SERIES_COLORS[0]
    keyColorIdx[key] = idx
  }
  activeColorIndices.add(keyColorIdx[key])
  return SERIES_COLORS[keyColorIdx[key]]
}

function releaseColor(key) {
  if (keyColorIdx[key] !== undefined) {
    activeColorIndices.delete(keyColorIdx[key])
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPoll() {
  if (pollTimer) return
  pollTimer = setInterval(tick, POLL_INTERVAL_MS)
}

function sinceTForIncremental(curve) {
  // 优先用本曲线水位（随每次成功落点推进）；否则用末点；再否则用查询基线
  if (curve.cursorT != null) return curve.cursorT
  const last = lastPointTime(curve)
  if (last != null) return last
  if (globalClearedAt.value != null) return globalClearedAt.value
  return undefined
}

function sinceTForInitial(curve) {
  // 首次/查询：用该曲线基线或全局查询起始时间
  if (curve?.baselineT != null) return curve.baselineT
  return globalClearedAt.value ?? undefined
}

function lastPointTime(curve) {
  if (!curve.points?.length) return null
  const t = Number(curve.points[curve.points.length - 1][0])
  return Number.isFinite(t) ? t : null
}

function advanceCursor(curve) {
  const last = lastPointTime(curve)
  if (last == null) return
  curve.cursorT = curve.cursorT == null ? last : Math.max(curve.cursorT, last)
}

function normalizePoints(rawPoints) {
  const out = []
  for (const p of rawPoints || []) {
    const t = Number(Array.isArray(p) ? p[0] : p?.t)
    const v = Array.isArray(p) ? p[1] : p?.v
    if (!Number.isFinite(t)) continue
    out.push([t, v])
  }
  return out
}

function mergePoints(existing, incoming, maxLen) {
  if (!incoming.length) return existing
  const map = new Map(existing.map(p => [p[0], p[1]]))
  for (const [t, v] of incoming) map.set(t, v)
  let merged = Array.from(map.entries()).sort((a, b) => a[0] - b[0])
  if (merged.length > maxLen) merged = merged.slice(-maxLen)
  return merged
}

async function loadPages() {
  const res = await getTelemetryConfig()
  tmPages.value = (res.data.page || []).filter(p => p.key && p.key.length <= 2)
}

async function loadFields() {
  const res = await getTelemetryFields(tmType.value)
  fields.value = res.data || []
  if (field.value && !fields.value.some(f => f.id === field.value)) {
    field.value = fields.value[0]?.id || ''
  } else if (!field.value && fields.value.length) {
    field.value = fields.value[0].id
  }
}

function buildBatchItem(curve, { initial = false } = {}) {
  const sinceT = initial ? sinceTForInitial(curve) : sinceTForIncremental(curve)
  const item = {
    deviceId: curve.deviceId,
    type: curve.tmType,
    field: curve.field,
    limit: initial ? CURVE_FETCH_LIMIT : (sinceT != null ? CURVE_INCREMENT_LIMIT : CURVE_FETCH_LIMIT)
  }
  if (sinceT != null) item.sinceT = sinceT
  return item
}

async function fetchCurvesBatch(curveList, { initial = false } = {}) {
  if (!curveList.length) return []
  const items = curveList.map(c => buildBatchItem(c, { initial }))
  const res = await getTelemetryCurveDataBatch(items)
  return res.data || []
}

function applyBatchRows(rows, { forceToPoints = false, replace = false } = {}) {
  for (const row of rows) {
    const type = String(row.type || '').toUpperCase()
    const key = curveKey(row.deviceId, type, row.field)
    const curve =
      curves.value.find(c => c.key === key) ||
      curves.value.find(
        c => c.deviceId === row.deviceId && c.tmType === type && c.field === row.field
      )
    if (!curve) continue
    curve.name = row.name || curve.field
    curve.unit = row.unit || ''
    const points = normalizePoints(row.points)
    if (forceToPoints || autoRefresh.value) {
      curve.points = replace ? points : mergePoints(curve.points, points, CURVE_DISPLAY_MAX)
    } else {
      curve.pauseCache = mergePoints(curve.pauseCache, points, CURVE_PAUSE_CACHE_MAX)
      // 暂停刷新时仍推进水位，避免恢复后 sinceT 卡住回拉旧段
      if (points.length) {
        const last = points[points.length - 1][0]
        curve.cursorT = curve.cursorT == null ? last : Math.max(curve.cursorT, last)
      }
      continue
    }
    advanceCursor(curve)
  }
}

async function tick() {
  if (tickBusy || querying.value || !curves.value.length) return
  tickBusy = true
  try {
    const rows = await fetchCurvesBatch(curves.value)
    applyBatchRows(rows)
    if (autoRefresh.value) {
      tsChart.captureFrozenZoom()
      tsChart.updateSeriesOnly()
      tsChart.applyViewAfterData()
    }
  } catch {
    /* 忽略单次失败 */
  } finally {
    tickBusy = false
  }
}

function flushPauseCache() {
  for (const curve of curves.value) {
    if (!curve.pauseCache?.length) continue
    curve.points = mergePoints(curve.points, curve.pauseCache, CURVE_DISPLAY_MAX)
    curve.pauseCache = []
    advanceCursor(curve)
  }
}

async function queryFromStartTime() {
  if (!curves.value.length) {
    ElMessage.warning('请先增加曲线')
    return
  }
  const startMs = parseQueryStartMs()
  if (!Number.isFinite(startMs) || startMs <= 0) {
    ElMessage.warning('请选择有效的起始时间')
    return
  }
  tsChart.exitCropMode({ silent: true })
  querying.value = true
  stopPoll()
  try {
    globalClearedAt.value = startMs
    for (const curve of curves.value) {
      curve.points = []
      curve.pauseCache = []
      curve.baselineT = startMs
      curve.cursorT = startMs
    }
    const rows = await fetchCurvesBatch(curves.value, { initial: true })
    applyBatchRows(rows, { forceToPoints: true, replace: true })
    tsChart.resetTimeWindow()
    nextTick(() => syncQueryStartFromChart({ force: true }))
    ElMessage.success('已按起始时间重新查询')
  } catch {
    ElMessage.error('查询失败，请稍后重试')
  } finally {
    querying.value = false
    if (curves.value.length) startPoll()
  }
}

function onToggleCrop() {
  tsChart.toggleCropMode({ hasSeries: curves.value.length > 0 })
}

function exportCurveCsv() {
  if (!curves.value.length) {
    ElMessage.warning('请先增加曲线')
    return
  }
  tsChart.captureFrozenZoom()
  const win = tsChart.getTimeWindow()
  if (!win) {
    ElMessage.warning('无法获取当前时间窗口')
    return
  }
  const seriesList = curves.value.map(c => ({
    name: `${c.field} ${c.name}${c.unit ? `(${c.unit})` : ''}`.trim(),
    points: c.points
  }))
  const { headers, rows } = buildAlignedSeriesTable(seriesList, win)
  if (!rows.length) {
    ElMessage.warning('当前时间窗口内无数据点可导出')
    return
  }
  const stamp = formatCsvDateTime(Date.now()).replace(/[: ]/g, '-').replace(/\./g, '_')
  exportCsvFile({
    headers,
    rows,
    filename: `telemetry-curve-${stamp}.csv`
  })
  ElMessage.success(`已导出 ${rows.length} 行（${headers.length - 1} 条曲线）`)
}

function onCurveAction() {
  if (isCurrentOnChart.value) removeCurve(currentCurveKey.value)
  else addCurve()
}

async function addCurve() {
  if (isCurrentOnChart.value) return
  if (curves.value.length >= MAX_CURVES) {
    ElMessage.warning(`最多同时显示 ${MAX_CURVES} 条曲线（颜色数量上限）`)
    return
  }
  if (!field.value) {
    ElMessage.warning('请选择遥测量')
    return
  }
  const key = curveKey(deviceId.value, tmType.value, field.value)
  adding.value = true
  try {
    const stub = {
      key,
      deviceId: deviceId.value,
      tmType: tmType.value,
      field: field.value,
      name: '',
      unit: '',
      color: acquireColor(key),
      points: [],
      pauseCache: [],
      baselineT: globalClearedAt.value ?? null,
      cursorT: globalClearedAt.value ?? null
    }
    const rows = await fetchCurvesBatch([stub], { initial: true })
    const row = rows[0] || {}
    stub.name = row.name || field.value
    stub.unit = row.unit || ''
    stub.points = normalizePoints(row.points)
    advanceCursor(stub)
    curves.value.push(stub)
    localStorage.setItem(ACTIVE_KEY, deviceId.value)
    startPoll()
    tsChart.render()
    tsChart.scheduleResize()
    nextTick(() => syncQueryStartFromChart({ force: true }))
  } finally {
    adding.value = false
  }
}

function removeCurve(key) {
  const curve = curves.value.find(c => c.key === key)
  if (!curve) return
  releaseColor(key)
  curves.value = curves.value.filter(c => c.key !== key)
  if (!curves.value.length) {
    stopPoll()
    tsChart.exitCropMode({ silent: true })
  }
  tsChart.render({ full: true })
}

function onTypeChange() {
  loadFields()
}

function shouldAutoAdd() {
  return route.query.from === 'table' && !!route.query.field
}

async function applyRouteAndAdd() {
  if (!shouldAutoAdd()) return
  if (route.query.type) tmType.value = String(route.query.type).toUpperCase()
  field.value = String(route.query.field)
  await loadFields()
  if (!field.value || isCurrentOnChart.value) return
  await addCurve()
}

async function bootstrap() {
  await loadPages()
  const ch = await listCanChannels()
  const list = (ch.data || []).map(d => d.deviceId).filter(Boolean)
  if (list.length) deviceOptions.value = list
  await loadFields()
  tsChart.init()
  if (shouldAutoAdd()) await applyRouteAndAdd()
  else tsChart.scheduleResize()
  nextTick(() => syncQueryStartFromChart({ force: !queryStartAt.value }))
}

watch(autoRefresh, val => {
  if (val) {
    flushPauseCache()
    tsChart.render()
  }
})

watch([zoomX, zoomY], () => {
  tsChart.refreshZoomBindings()
})

watch(
  () => [route.query.type, route.query.field, route.query.from],
  async ([type, fld, from], old) => {
    if (from !== 'table' || !fld) return
    const [oldType, oldFld, oldFrom] = old || []
    if (type === oldType && fld === oldFld && from === oldFrom) return
    await applyRouteAndAdd()
  }
)

onMounted(async () => {
  await bootstrap()
  window.addEventListener('resize', tsChart.resize)
})

onActivated(async () => {
  if (shouldAutoAdd()) {
    const nextKey = curveKey(
      deviceId.value,
      String(route.query.type || tmType.value).toUpperCase(),
      String(route.query.field)
    )
    if (!curves.value.some(c => c.key === nextKey)) {
      await applyRouteAndAdd()
    }
  }
  if (curves.value.length) {
    await tick()
    startPoll()
  }
  tsChart.scheduleResize()
})

onDeactivated(() => {
  tsChart.exitCropMode({ silent: true })
  stopPoll()
})

onBeforeUnmount(() => {
  stopPoll()
  window.removeEventListener('resize', tsChart.resize)
  tsChart.dispose()
})
</script>

<style scoped>
.curve-page {
  padding: 12px 16px !important;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.toolbar-row {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
}
.toolbar {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
}
.toolbar :deep(.el-form-item) {
  margin-bottom: 8px;
}
.icon-tool-group {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 6px;
  flex-shrink: 0;
}
.icon-tool-wrap {
  display: inline-flex;
  line-height: 0;
}
.icon-tool-btn {
  width: 20px !important;
  height: 20px !important;
  min-width: 20px !important;
  margin: 0 !important;
  padding: 0 !important;
}
.icon-tool-btn :deep(.el-icon) {
  font-size: 12px;
}
.toolbar-options {
  flex-shrink: 0;
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.toolbar-options :deep(.el-form-item) {
  margin-bottom: 4px;
  margin-right: 20px;
}
.curve-legend {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 6px 0 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-label {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legend-remove {
  width: 20px !important;
  height: 20px !important;
  padding: 0 !important;
  border: none;
  color: var(--el-text-color-secondary);
}
.chart-wrap {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
}
.chart-box {
  width: 100%;
  height: 100%;
}
.empty-hint {
  position: absolute;
  left: 12px;
  top: 8px;
  z-index: 1;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  pointer-events: none;
}
.action-btn {
  min-width: 88px;
}
</style>
