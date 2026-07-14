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
      <el-form-item label="结束时间">
        <el-date-picker
          v-model="queryEndAt"
          type="datetime"
          placeholder="选择结束时间"
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
          @click="queryFromTimeRange"
        >
          查询
        </el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置</el-button>
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
      <div v-if="!curves.length" class="empty-hint">请选择遥测量后点击「增加曲线」，再选择时间区间查询</div>
      <div ref="chartRef" class="chart-box" />
    </div>
  </div>
</template>

<script setup name="TelemetryArchive">
import { Close, Crop, Download } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTelemetryConfig } from '@/api/payload/config'
import { getTelemetryFields, getTelemetryHistoryCurveDataBatch } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'
import { useTimeSeriesChart } from '@/components/TimeSeriesChart'
import { buildAlignedSeriesTable, exportCsvFile, formatCsvDateTime } from '@/utils/csvExport'

const CURVE_FETCH_LIMIT = 50000
const DEFAULT_RANGE_MS = 10 * 60 * 1000
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000
const MAX_CURVES = 10

const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]

const route = useRoute()
const ACTIVE_KEY = 'payload:activeDeviceId'
const chartRef = ref(null)
const keyColorIdx = {}
const activeColorIndices = new Set()

const tmPages = ref([])
const tmType = ref((route.query.type || 'FF').toString().toUpperCase())
const field = ref(route.query.field ? String(route.query.field) : '')
const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
const fields = ref([])
const curves = ref([])
const adding = ref(false)
const zoomX = ref(true)
const zoomY = ref(true)
const queryStartAt = ref('')
const queryEndAt = ref('')
const querying = ref(false)
const queryRange = ref({ startT: null, endT: null })

function formatDateTimeSec(ms) {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function parseDateTimeMs(text) {
  if (!text) return NaN
  return Date.parse(String(text).replace(/-/g, '/'))
}

function initDefaultTimeRange() {
  const end = Date.now()
  const start = end - DEFAULT_RANGE_MS
  queryEndAt.value = formatDateTimeSec(end)
  queryStartAt.value = formatDateTimeSec(start)
  queryRange.value = { startT: start, endT: end }
}

function parseQueryRange() {
  const startMs = parseDateTimeMs(queryStartAt.value)
  const endMs = parseDateTimeMs(queryEndAt.value)
  if (!Number.isFinite(startMs) || startMs <= 0) return null
  if (!Number.isFinite(endMs) || endMs <= 0) return null
  if (startMs > endMs) return null
  return { startT: startMs, endT: endMs }
}

function syncQueryStartFromChart({ force = false } = {}) {
  if (!force && queryStartAt.value) return
  const win = tsChart.getTimeWindow()
  let start = win?.start
  if (start == null || !Number.isFinite(Number(start)) || Number(start) <= 0) {
    start = tsChart.getEarliestTime() || Date.now() - DEFAULT_RANGE_MS
  }
  start = Number(start)
  if (!Number.isFinite(start) || start < 946684800000) {
    start = Date.now() - DEFAULT_RANGE_MS
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

/** 颜色池：占用表 + 偏好色；偏好被占则改分空闲色，避免重复 */
function acquireColor(key) {
  const prefer = keyColorIdx[key]
  if (prefer !== undefined && !activeColorIndices.has(prefer)) {
    activeColorIndices.add(prefer)
    return SERIES_COLORS[prefer]
  }
  let idx = 0
  while (idx < SERIES_COLORS.length && activeColorIndices.has(idx)) idx++
  if (idx >= SERIES_COLORS.length) {
    idx = 0
  }
  keyColorIdx[key] = idx
  activeColorIndices.add(idx)
  return SERIES_COLORS[idx]
}

function releaseColor(key) {
  const idx = keyColorIdx[key]
  if (idx === undefined) return
  activeColorIndices.delete(idx)
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

function buildBatchItem(curve) {
  const range = queryRange.value
  return {
    deviceId: curve.deviceId,
    type: curve.tmType,
    field: curve.field,
    startT: range.startT,
    endT: range.endT,
    limit: CURVE_FETCH_LIMIT
  }
}

async function fetchCurvesBatch(curveList) {
  if (!curveList.length) return []
  const range = parseQueryRange()
  if (!range) {
    ElMessage.warning('请选择有效的时间区间')
    return []
  }
  queryRange.value = range
  const items = curveList.map(c => buildBatchItem(c))
  const res = await getTelemetryHistoryCurveDataBatch(items)
  return res.data || []
}

function applyBatchRows(rows) {
  for (const row of rows) {
    const type = String(row.type || '').toUpperCase()
    const key = curveKey(row.deviceId, type, row.field)
    const curve = curves.value.find(c => c.key === key)
    if (!curve) continue
    curve.name = row.name || curve.field
    curve.unit = row.unit || ''
    curve.points = normalizePoints(row.points)
  }
}

async function queryFromTimeRange() {
  if (!curves.value.length) {
    ElMessage.warning('请先增加曲线')
    return
  }
  const range = parseQueryRange()
  if (!range) {
    ElMessage.warning('请选择有效的时间区间（起始时间不能晚于结束时间）')
    return
  }
  tsChart.exitCropMode({ silent: true })
  querying.value = true
  try {
    queryRange.value = range
    for (const curve of curves.value) {
      curve.points = []
    }
    const rows = await fetchCurvesBatch(curves.value)
    applyBatchRows(rows)
    tsChart.resetTimeWindow()
    nextTick(() => syncQueryStartFromChart({ force: true }))
    ElMessage.success('已按时间区间加载归档数据')
  } catch {
    ElMessage.error('查询失败，请稍后重试')
  } finally {
    querying.value = false
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
    filename: `telemetry-archive-${stamp}.csv`
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
      points: []
    }
    const range = parseQueryRange()
    if (range) {
      queryRange.value = range
      const rows = await fetchCurvesBatch([stub])
      const row = rows[0] || {}
      stub.name = row.name || field.value
      stub.unit = row.unit || ''
      stub.points = normalizePoints(row.points)
    } else {
      stub.name = fields.value.find(f => f.id === field.value)?.name || field.value
    }
    curves.value.push(stub)
    localStorage.setItem(ACTIVE_KEY, deviceId.value)
    tsChart.render()
    tsChart.scheduleResize()
    nextTick(() => syncQueryStartFromChart({ force: !queryStartAt.value }))
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
    tsChart.exitCropMode({ silent: true })
  }
  tsChart.render({ full: true })
}

function onTypeChange() {
  loadFields()
}

async function bootstrap() {
  initDefaultTimeRange()
  await loadPages()
  const ch = await listCanChannels()
  const list = (ch.data || []).map(d => d.deviceId).filter(Boolean)
  if (list.length) deviceOptions.value = list
  await loadFields()
  tsChart.init()
  tsChart.scheduleResize()
}

watch([zoomX, zoomY], () => {
  tsChart.refreshZoomBindings()
})

onMounted(async () => {
  await bootstrap()
  window.addEventListener('resize', tsChart.resize)
})

onBeforeUnmount(() => {
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
