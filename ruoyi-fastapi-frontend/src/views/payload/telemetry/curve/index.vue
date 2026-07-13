<template>
  <div class="app-container curve-page">
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

    <el-form :inline="true" class="toolbar-options">
      <el-form-item>
        <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="zoomX">X轴缩放</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="zoomY">Y轴缩放</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="resetTimeWindow">重置</el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="clearChartData">清理数据</el-button>
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
import * as echarts from 'echarts'
import { Close } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTelemetryConfig } from '@/api/payload/config'
import { getTelemetryCurveDataBatch, getTelemetryFields } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'

const CURVE_FETCH_LIMIT = 50000
const CURVE_INCREMENT_LIMIT = 500
const CURVE_DISPLAY_MAX = 50000
const CURVE_PAUSE_CACHE_MAX = 1000
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000
const POLL_INTERVAL_MS = 1000
const DATAZOOM_SLIDER_HEIGHT = 30
const LIVE_EDGE_THRESHOLD_MS = 2000
const MAX_CURVES = 10

const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]

const route = useRoute()
const ACTIVE_KEY = 'payload:activeDeviceId'
const chartRef = ref(null)
let chart = null
let pollTimer = null
let tickBusy = false
let viewWindowMs = DEFAULT_VIEW_WINDOW_MS
let frozenZoom = null
let liveFollow = true
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

/** 增量拉取：已有末点时从末点之后；否则有清理时间则从清理时间之后；否则不传（全量） */
function sinceTForIncremental(curve) {
  const last = lastPointTime(curve)
  if (last != null) return last
  if (globalClearedAt.value != null) return globalClearedAt.value
  return undefined
}

/** 首次添加/重新添加：有清理时间则从清理时间之后；否则不传 sinceT（从 Redis 取最近全量） */
function sinceTForInitial() {
  return globalClearedAt.value ?? undefined
}

function lastPointTime(curve) {
  if (!curve.points?.length) return null
  return curve.points[curve.points.length - 1][0]
}

function mergePoints(existing, incoming, maxLen) {
  if (!incoming.length) return existing
  const map = new Map(existing.map(p => [p[0], p[1]]))
  for (const [t, v] of incoming) map.set(t, v)
  let merged = Array.from(map.entries()).sort((a, b) => a[0] - b[0])
  if (merged.length > maxLen) merged = merged.slice(-maxLen)
  return merged
}

function getLatestTime() {
  let max = 0
  for (const c of curves.value) {
    for (const p of c.points) {
      if (p[0] > max) max = p[0]
    }
  }
  return max
}

function getEarliestTime() {
  let min = Infinity
  for (const c of curves.value) {
    for (const p of c.points) {
      if (p[0] < min) min = p[0]
    }
  }
  return Number.isFinite(min) ? min : 0
}

function isEndAtLatest(endValue) {
  const latest = getLatestTime() || Date.now()
  return Math.abs(latest - endValue) <= LIVE_EDGE_THRESHOLD_MS
}

function readFrozenZoom() {
  if (!chart) return null
  const opt = chart.getOption()
  const zooms = opt?.dataZoom || []
  const slider = zooms.find(z => z.type === 'slider')
  const inside = zooms.find(z => z.type === 'inside')
  const pick = slider || inside
  if (!pick) return null
  const z = {
    start: pick.start,
    end: pick.end,
    startValue: pick.startValue,
    endValue: pick.endValue
  }
  const yAxis = opt.yAxis?.[0]
  if (yAxis?.min != null && yAxis.min !== 'dataMin') z.yMin = yAxis.min
  if (yAxis?.max != null && yAxis.max !== 'dataMax') z.yMax = yAxis.max
  return z
}

function captureFrozenZoom() {
  frozenZoom = readFrozenZoom()
}

function buildInsideZoom(z) {
  const cfg = {
    type: 'inside',
    filterMode: 'none',
    xAxisIndex: zoomX.value ? [0] : [],
    yAxisIndex: zoomY.value ? [0] : []
  }
  if (z?.startValue != null && z?.endValue != null) {
    cfg.startValue = z.startValue
    cfg.endValue = z.endValue
  } else if (z?.start != null && z?.end != null) {
    cfg.start = z.start
    cfg.end = z.end
  }
  return cfg
}

function buildSliderZoom(z) {
  const cfg = {
    type: 'slider',
    xAxisIndex: [0],
    bottom: 8,
    height: DATAZOOM_SLIDER_HEIGHT,
    brushSelect: false,
    showDetail: true,
    showDataShadow: false
  }
  if (z?.startValue != null && z?.endValue != null) {
    cfg.startValue = z.startValue
    cfg.endValue = z.endValue
  } else if (z?.start != null && z?.end != null) {
    cfg.start = z.start
    cfg.end = z.end
  }
  return cfg
}

function clampWindow(start, end) {
  const earliest = getEarliestTime()
  const latest = getLatestTime() || Date.now()
  let s = start
  let e = end
  if (e > latest + LIVE_EDGE_THRESHOLD_MS) e = latest
  if (s < earliest) s = earliest
  if (e <= s) s = Math.max(earliest, e - DEFAULT_VIEW_WINDOW_MS)
  return { startValue: s, endValue: e }
}

function buildLiveFollowZoom() {
  const end = getLatestTime() || Date.now()
  const earliest = getEarliestTime()
  let start = end - viewWindowMs
  if (earliest && start < earliest) start = earliest
  if (end <= start) start = end - DEFAULT_VIEW_WINDOW_MS
  return clampWindow(start, end)
}

function buildSeries() {
  return curves.value.map(c => ({
    id: c.key,
    name: `${c.field} ${c.name}`,
    type: 'line',
    showSymbol: false,
    data: c.points,
    itemStyle: { color: c.color },
    lineStyle: { color: c.color }
  }))
}

function restoreViewState(z) {
  if (!chart || !z) return
  const patch = {
    dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
  }
  if (z.yMin != null || z.yMax != null) {
    patch.yAxis = { scale: true, min: z.yMin, max: z.yMax }
  }
  chart.setOption(patch)
}

function updateSeriesOnly() {
  if (!chart) return
  const patch = { series: buildSeries() }
  const z = frozenZoom || readFrozenZoom()
  if (z && (z.yMin != null || z.yMax != null)) {
    patch.yAxis = { scale: true, min: z.yMin, max: z.yMax }
  }
  chart.setOption(patch, { replaceMerge: ['series'], lazyUpdate: true })
}

function applyViewAfterData() {
  if (!chart) return
  if (liveFollow) {
    const z = buildLiveFollowZoom()
    frozenZoom = z
    chart.setOption({
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
    })
  } else {
    restoreViewState(frozenZoom || readFrozenZoom())
  }
}

function renderChart({ full = false } = {}) {
  if (!chart) return
  const series = buildSeries()

  if (full || !series.length) {
    const z = buildLiveFollowZoom()
    liveFollow = true
    frozenZoom = z
    chart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 55, right: 20, top: 16, bottom: DATAZOOM_SLIDER_HEIGHT + 36 },
      xAxis: { type: 'time' },
      yAxis: { type: 'value', scale: true },
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)],
      series
    }, { notMerge: true })
    scheduleResize()
    return
  }

  updateSeriesOnly()
  applyViewAfterData()
}

function scheduleResize() {
  nextTick(() => {
    chart?.resize()
    requestAnimationFrame(() => chart?.resize())
  })
}

function onDataZoom() {
  const z = readFrozenZoom()
  if (z?.endValue != null) {
    liveFollow = isEndAtLatest(z.endValue)
    if (liveFollow && z.startValue != null) {
      viewWindowMs = Math.max(1000, z.endValue - z.startValue)
    }
  }
  captureFrozenZoom()
}

function resetTimeWindow() {
  liveFollow = true
  viewWindowMs = DEFAULT_VIEW_WINDOW_MS
  const z = buildLiveFollowZoom()
  frozenZoom = z
  if (chart) {
    chart.setOption({
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)],
      yAxis: { scale: true }
    })
  }
  renderChart()
}

function initChart() {
  if (!chartRef.value || chart) return
  chart = echarts.init(chartRef.value)
  chart.on('datazoom', onDataZoom)
  renderChart({ full: true })
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
  const sinceT = initial ? sinceTForInitial() : sinceTForIncremental(curve)
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

function applyBatchRows(rows) {
  for (const row of rows) {
    const key = curveKey(row.deviceId, row.type, row.field)
    const curve = curves.value.find(c => c.key === key)
    if (!curve) continue
    curve.name = row.name || curve.field
    curve.unit = row.unit || ''
    const points = (row.points || []).map(p => [p.t, p.v])
    if (autoRefresh.value) {
      curve.points = mergePoints(curve.points, points, CURVE_DISPLAY_MAX)
    } else {
      curve.pauseCache = mergePoints(curve.pauseCache, points, CURVE_PAUSE_CACHE_MAX)
    }
  }
}

async function tick() {
  if (tickBusy || !curves.value.length) return
  tickBusy = true
  try {
    const rows = await fetchCurvesBatch(curves.value)
    applyBatchRows(rows)
    if (autoRefresh.value) {
      captureFrozenZoom()
      updateSeriesOnly()
      applyViewAfterData()
    }
  } catch {
    /* 忽略单次失败，避免与防重复提交叠加 */
  } finally {
    tickBusy = false
  }
}

function flushPauseCache() {
  for (const curve of curves.value) {
    if (!curve.pauseCache?.length) continue
    curve.points = mergePoints(curve.points, curve.pauseCache, CURVE_DISPLAY_MAX)
    curve.pauseCache = []
  }
}

function clearChartData() {
  const now = Date.now()
  globalClearedAt.value = now
  for (const curve of curves.value) {
    curve.points = []
    curve.pauseCache = []
  }
  liveFollow = true
  viewWindowMs = DEFAULT_VIEW_WINDOW_MS
  resetTimeWindow()
  ElMessage.success('已清理图表数据，将从当前时间起重新累积')
}

function onCurveAction() {
  if (isCurrentOnChart.value) {
    removeCurve(currentCurveKey.value)
  } else {
    addCurve()
  }
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
    // 帧到即全字段落库，增加曲线只需拉数显示
    const stub = {
      key,
      deviceId: deviceId.value,
      tmType: tmType.value,
      field: field.value,
      name: '',
      unit: '',
      color: acquireColor(key),
      points: [],
      pauseCache: []
    }
    const rows = await fetchCurvesBatch([stub], { initial: true })
    const row = rows[0] || {}
    stub.name = row.name || field.value
    stub.unit = row.unit || ''
    stub.points = (row.points || []).map(p => [p.t, p.v])
    curves.value.push(stub)
    localStorage.setItem(ACTIVE_KEY, deviceId.value)
    startPoll()
    renderChart()
    scheduleResize()
  } finally {
    adding.value = false
  }
}

function removeCurve(key) {
  const curve = curves.value.find(c => c.key === key)
  if (!curve) return
  releaseColor(key)
  curves.value = curves.value.filter(c => c.key !== key)
  if (!curves.value.length) stopPoll()
  renderChart({ full: true })
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
  initChart()
  if (shouldAutoAdd()) await applyRouteAndAdd()
  else scheduleResize()
}

function onResize() {
  chart?.resize()
}

watch(autoRefresh, val => {
  if (val) {
    flushPauseCache()
    renderChart()
  }
})

watch([zoomX, zoomY], () => {
  captureFrozenZoom()
  const z = frozenZoom || readFrozenZoom()
  if (chart && z) {
    chart.setOption({
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
    })
  }
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
  window.addEventListener('resize', onResize)
})

onActivated(async () => {
  // keep-alive 场景：页面重新激活时恢复轮询，并按末点时间增量补数据
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
  scheduleResize()
})

onDeactivated(() => {
  // keep-alive 场景：切走页面立即停止轮询，避免后台持续请求
  stopPoll()
})

onBeforeUnmount(() => {
  stopPoll()
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
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
.toolbar {
  flex-shrink: 0;
  margin-bottom: 0;
}
.toolbar :deep(.el-form-item) {
  margin-bottom: 8px;
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
