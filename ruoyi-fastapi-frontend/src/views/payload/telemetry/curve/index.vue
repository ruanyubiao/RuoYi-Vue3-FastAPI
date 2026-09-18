<template>
  <div class="app-container curve-page">
    <div class="toolbar-row">
      <el-form :inline="true" label-width="70px" class="toolbar">
        <el-form-item label="遥测表">
          <TelemetryPageSelect v-model="tmSelect" :pages="tmPages" style="width: 280px" @change="onTypeChange" />
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
      <CurveChartTools
        :crop-mode="cropMode"
        :disabled="!curves.length"
        @crop="onToggleCrop"
        @export="exportCurveCsv"
      />
    </div>

    <el-form :inline="true" label-width="70px" class="toolbar-options">
      <el-form-item label="起始时间">
        <el-date-picker
          v-model="queryStartAt"
          type="datetime"
          placeholder="选择起始时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          format="YYYY-MM-DD HH:mm:ss"
          :clearable="false"
          style="width: 220px"
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
        <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置曲线</el-button>
      </el-form-item>
      <el-form-item>
        <el-select v-model="downsampleRatio" style="width: 140px" @change="writeCurvePrefs">
          <el-option
            v-for="opt in downsampleOptions"
            :key="String(opt.value)"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <span class="curve-fps">帧率 {{ fpsText }}</span>
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
      </el-form-item>
    </el-form>

    <CurveLegend :curves="curves" @remove="removeCurve" />

    <div class="chart-wrap">
      <div v-if="!curves.length" class="empty-hint">请选择遥测量后点击「增加曲线」</div>
      <TimeSeriesChart
        ref="tsChart"
        :get-series="getChartSeries"
        :get-series-points="getChartPoints"
        :show-controls="curves.length > 0"
        :default-view-window-ms="DEFAULT_VIEW_WINDOW_MS"
        @view-change="onChartViewChange"
      />
    </div>
  </div>
</template>

<script setup name="Curve">
import { markRaw } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import cache from '@/plugins/cache'
import { loadTelemetryPagesCached } from '@/utils/telemetryPages'
import { getTelemetryCurveDataBatch, getTelemetryFields } from '@/api/payload/telemetry'
import { CurveChartTools, CurveLegend, TimeSeriesChart } from '@/components/TimeSeriesChart'
import { exportChartWindowCsv, MAX_CURVES, curveKey, normalizePoints, useCurveChartPage } from '@/utils/curvePage'
import {
  CURVE_DRIP_INTERVAL_MS,
  CURVE_POLL_INTERVAL_MS,
  applyLiveFetch,
  dripBatchSize,
  dripBufferLength,
  dropFutureCurvePoints,
  incrementalSinceT,
  mergePoints,
  nextFetchCursor,
  reserveSinceT,
  sanitizeSinceT,
  takeLiveDrip
} from '@/utils/curveDrip'
import {
  CURVE_DOWNSAMPLE_RATIOS,
  downsampleMinMax
} from '@/utils/curveDownsample'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

/** 首次/查询拉取上限 */
const CURVE_FETCH_LIMIT = 20000
/** 增量轮询每条曲线点数 */
const CURVE_INCREMENT_LIMIT = 20000
const CURVE_DISPLAY_MAX = 20000
/** 暂停自动刷新时暂存的增量点数（与上屏上限一致，避免恢复后缺口） */
const CURVE_PAUSE_CACHE_MAX = CURVE_DISPLAY_MAX
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000
const POLL_INTERVAL_MS = CURVE_POLL_INTERVAL_MS

const CURVE_PREFS_KEY = 'payload:curve:prefs:v1'
const downsampleOptions = [
  { value: 0, label: '数据不抽样' },
  ...CURVE_DOWNSAMPLE_RATIOS.map(n => ({ value: n, label: `降采样${n}倍` }))
]

function writeCurvePrefs() {
  cache.local.setJSON(CURVE_PREFS_KEY, {
    tmSelect: tmSelect.value || '',
    field: field.value || '',
    downsampleRatio: downsampleRatio.value
  })
}

const curvePrefs = cache.local.getJSON(CURVE_PREFS_KEY, {}) || {}
/** 0=不抽样；N=每 2N 点保留峰谷。默认 10×，5000Hz 全量上屏会卡。 */
const _savedRatio = Number(curvePrefs.downsampleRatio)
const downsampleRatio = ref(Number.isFinite(_savedRatio) && _savedRatio >= 0 ? _savedRatio : 10)
const recvFps = ref(0)
const fpsText = computed(() => {
  const n = Number(recvFps.value)
  if (!Number.isFinite(n) || n < 0) return '0 Hz'
  return `${Math.round(n)} Hz`
})

const route = useRoute()
const router = useRouter()
const tsChart = ref(null)
let pollTimer = null
let dripTimer = null
let tickBusy = false
/** 丢弃过期的 in-flight 轮询（HMR 双定时器、加曲线与 tick 重叠） */
let pollGen = 0
/** 各条缓存长度未齐时暂停滴灌：轮询仍跑，长度不一致则整批上屏 */
let holdDrip = false
/** 查询/清空后的全局起始水位(ms) */
const globalClearedAt = ref(null)

const tmPages = ref([])
const tmSelect = ref('') // 存储键 BIU:FF / XL:FF
/** 当前选中的遥测量 id */
const field = ref(
  route.query.field ? String(route.query.field) : String(curvePrefs.field || '')
)
const fields = ref([])

/** 当前表存储键（大写） */
const tmType = computed(() => String(tmSelect.value || '').toUpperCase())
/** 表所属 family（xl/biu），拉字段与曲线数据用 */
const tmFamily = computed(() => {
  const hit = tmPages.value.find(p => p.key === tmSelect.value || p.key === tmType.value)
  if (hit?.family) return String(hit.family).toLowerCase()
  const s = tmType.value
  const i = s.indexOf(':')
  if (i > 0) return s.slice(0, i).toLowerCase()
  return 'biu'
})

/** 已上图曲线；同一时刻只允许一张遥测表 */
const curves = ref([])
const adding = ref(false)
const autoRefresh = ref(true)
/** 查询起始时间：YYYY-MM-DD HH:mm:ss，初始对齐底部时间轴起点 */
const queryStartAt = ref('')
const querying = ref(false)
const { acquireColor, releaseColor, cropMode, getChartSeries, getChartPoints, onToggleCrop } = useCurveChartPage(
  tsChart,
  curves
)

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
  const win = tsChart.value?.getTimeWindow()
  let start = win?.start
  if (start == null || !Number.isFinite(Number(start)) || Number(start) <= 0) {
    start = tsChart.value?.getEarliestTime() || Date.now()
  }
  start = Number(start)
  // 过滤异常时间（例如解析错误导致的历史年）
  if (!Number.isFinite(start) || start < 946684800000) {
    // < 2000-01-01
    start = Date.now()
  }
  queryStartAt.value = formatDateTimeSec(start)
}

const currentCurveKey = computed(() => {
  if (!field.value) return ''
  return curveKey(tmType.value, field.value)
})

const isCurrentOnChart = computed(() => {
  if (!currentCurveKey.value) return false
  return curves.value.some(c => c.key === currentCurveKey.value)
})

const curveActionDisabled = computed(() => !field.value || adding.value)

function onChartViewChange() {
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

function onResetTimeWindow() {
  tsChart.value?.resetTimeWindow()
  nextTick(() => syncQueryStartFromChart({ force: true }))
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
  // 每条用自己的末点水位；未来 sinceT（旧时钟跑飞）丢弃，改拉最近一段。
  const t = sanitizeSinceT(reserveSinceT(curve?.sentSinceT, incrementalSinceT(curve)))
  if (t != null) return t
  if (globalClearedAt.value != null) return sanitizeSinceT(globalClearedAt.value) ?? undefined
  return undefined
}

function markSinceTSent(curve, t) {
  const reserved = reserveSinceT(curve?.sentSinceT, t)
  if (reserved != null) curve.sentSinceT = reserved
}

function sinceTForInitial(curve) {
  // 首次/查询：用该曲线基线或全局查询起始时间
  if (curve?.baselineT != null) return curve.baselineT
  return globalClearedAt.value ?? undefined
}

function pendingLen(curve) {
  return dripBufferLength(curve.pending, curve.pendingHead)
}

function pendingLive(curve) {
  const p = curve.pending || []
  const h = curve.pendingHead || 0
  return h > 0 ? p.slice(h) : p
}

function noteFetchCursor(curve, points) {
  curve.fetchCursorT = nextFetchCursor(curve.fetchCursorT, points)
}

function lastPointTime(curve) {
  if (!curve.points?.length) return null
  const t = Number(curve.points[curve.points.length - 1][0])
  return Number.isFinite(t) ? t : null
}

function advanceCursor(curve) {
  const last = curve.fetchCursorT != null ? curve.fetchCursorT : lastPointTime(curve)
  if (last == null) return
  curve.cursorT = curve.cursorT == null ? last : Math.max(curve.cursorT, last)
}

function rawPoints(points) {
  return markRaw(Array.isArray(points) ? points : [])
}

/** 拉全部遥测表页；优先路由 type，否则偏好或第一项 */
async function loadPages() {
  tmPages.value = (await loadTelemetryPagesCached()).filter(p => p.key)
  const qType = route.query.type ? String(route.query.type).toUpperCase() : ''
  const qFam = route.query.family ? String(route.query.family).toLowerCase() : ''
  let hit = null
  if (shouldAutoAdd() && qType) {
    hit =
      tmPages.value.find(p => p.key === qType) ||
      tmPages.value.find(
        p => (p.localKey || p.id) === qType && (!qFam || p.family === qFam)
      ) ||
      tmPages.value.find(p => (p.localKey || p.id) === qType)
  }
  if (!hit && curvePrefs.tmSelect) {
    hit = tmPages.value.find(p => p.key === curvePrefs.tmSelect)
  }
  if (!hit) hit = tmPages.value[0]
  if (hit) tmSelect.value = hit.key
}

/** 拉当前表字段列表；无效 field 则落到第一项 */
async function loadFields() {
  if (!tmType.value) {
    fields.value = []
    return
  }
  const res = await getTelemetryFields(tmType.value, tmFamily.value)
  fields.value = res.data || []
  if (field.value && !fields.value.some(f => f.id === field.value)) {
    field.value = fields.value[0]?.id || ''
  } else if (!field.value && fields.value.length) {
    field.value = fields.value[0].id
  }
}

/** 构造 batch 请求项：首次用 FETCH_LIMIT，增量用 sinceT + INCREMENT_LIMIT */
function buildBatchItem(curve, { initial = false } = {}) {
  const sinceT = initial ? sinceTForInitial(curve) : sinceTForIncremental(curve)
  const item = {
    type: curve.tmType,
    field: curve.field,
    limit: initial ? CURVE_FETCH_LIMIT : (sinceT != null ? CURVE_INCREMENT_LIMIT : CURVE_FETCH_LIMIT)
  }
  if (sinceT != null) {
    item.sinceT = sinceT
    if (!initial) markSinceTSent(curve, sinceT)
  }
  return item
}

async function fetchCurvesBatch(curveList, { initial = false, initialKeys } = {}) {
  if (!curveList.length) return []
  const extra = initialKeys instanceof Set ? initialKeys : null
  const items = curveList.map(c =>
    buildBatchItem(c, { initial: initial || extra?.has(c.key) })
  )
  const res = await getTelemetryCurveDataBatch(items, { fps: 1 })
  const payload = res.data
  if (payload && !Array.isArray(payload) && payload.fps != null) {
    const n = Number(payload.fps)
    recvFps.value = Number.isFinite(n) && n >= 0 ? n : 0
  }
  if (Array.isArray(payload)) return payload
  return payload?.items || []
}

/** 把 batch 行写入对应曲线；自动刷新增量进缓存，由滴灌在一窗内上屏。空拉取则剩余缓存立刻上屏。 */
function applyBatchRows(rows, { forceToPoints = false, replace = false } = {}) {
  let flushed = false
  for (const row of rows) {
    const type = String(row.type || '').toUpperCase()
    const key = curveKey(type, row.field)
    const curve =
      curves.value.find(c => c.key === key) ||
      curves.value.find(c => c.tmType === type && c.field === row.field)
    if (!curve) continue
    curve.name = row.name || curve.field
    curve.unit = row.unit || ''
    const points = downsampleMinMax(
      dropFutureCurvePoints(normalizePoints(row.points)),
      downsampleRatio.value
    )
    curve.points = rawPoints(dropFutureCurvePoints(curve.points))
    curve.pending = rawPoints(dropFutureCurvePoints(pendingLive(curve)))
    curve.pendingHead = 0
    curve.pauseCache = rawPoints(dropFutureCurvePoints(curve.pauseCache))
    curve.fetchCursorT = sanitizeSinceT(curve.fetchCursorT)
    curve.sentSinceT = sanitizeSinceT(curve.sentSinceT)
    curve.cursorT = sanitizeSinceT(curve.cursorT)
    if (replace) {
      curve.points = rawPoints(points)
      curve.pending = rawPoints([])
      curve.pendingHead = 0
      curve.pauseCache = rawPoints([])
      curve.dripBatch = 0
      noteFetchCursor(curve, points)
    } else if (forceToPoints) {
      curve.points = rawPoints(mergePoints(curve.points, points, CURVE_DISPLAY_MAX))
      noteFetchCursor(curve, points)
    } else if (autoRefresh.value) {
      const next = applyLiveFetch(curve.pending, points, CURVE_DISPLAY_MAX)
      if (next.flush.length) {
        curve.points = rawPoints(mergePoints(curve.points, next.flush, CURVE_DISPLAY_MAX))
        flushed = true
      }
      curve.pending = rawPoints(next.pending)
      curve.pendingHead = 0
      curve.dripBatch = next.pending.length ? dripBatchSize(dripBufferLength(next.pending)) : 0
      if (points.length) noteFetchCursor(curve, points)
    } else {
      curve.pauseCache = rawPoints(mergePoints(curve.pauseCache, points, CURVE_PAUSE_CACHE_MAX))
      if (points.length) {
        const last = points[points.length - 1][0]
        curve.cursorT = curve.cursorT == null ? last : Math.max(curve.cursorT, last)
        noteFetchCursor(curve, points)
      }
      continue
    }
    advanceCursor(curve)
  }
  return flushed
}

function cacheLen(curve) {
  return pendingLen(curve) + (curve.pauseCache?.length || 0)
}

function cachesAligned() {
  if (curves.value.length < 2) return true
  const n = cacheLen(curves.value[0])
  return curves.value.every(c => cacheLen(c) === n)
}

function paintLiveChart() {
  tsChart.value?.paintLiveFrame()
}

/** 把 pending / 暂停缓存一次性并入上屏点 */
function flushDripBuffers() {
  for (const curve of curves.value) {
    const incoming = []
    if (pendingLen(curve)) incoming.push(...pendingLive(curve))
    if (curve.pauseCache?.length) incoming.push(...curve.pauseCache)
    if (incoming.length) {
      curve.points = rawPoints(mergePoints(curve.points, incoming, CURVE_DISPLAY_MAX))
    }
    curve.pending = rawPoints([])
    curve.pendingHead = 0
    curve.dripBatch = 0
    curve.pauseCache = rawPoints([])
    advanceCursor(curve)
  }
}

/** 对齐期间：缓存长度不一致则整批刷上屏；一致才恢复滴灌 */
function applyHoldDripAfterFetch() {
  if (!holdDrip) return
  if (curves.value.length < 2) {
    holdDrip = false
    return
  }
  if (!cachesAligned()) {
    flushDripBuffers()
    paintLiveChart()
    return
  }
  holdDrip = false
}

/** 轮询增量点进缓存；上屏由 dripPending。对齐未完成时本轮直接刷图。 */
async function tick() {
  if (tickBusy || querying.value || adding.value || !curves.value.length) return
  tickBusy = true
  const gen = ++pollGen
  try {
    const rows = await fetchCurvesBatch(curves.value)
    if (gen !== pollGen || adding.value || querying.value) return
    const flushed = applyBatchRows(rows)
    applyHoldDripAfterFetch()
    if (flushed) paintLiveChart()
  } catch {
    /* 忽略单次失败 */
  } finally {
    tickBusy = false
  }
}

function dripPending() {
  if (holdDrip || !autoRefresh.value || querying.value || adding.value || !curves.value.length) return
  let changed = false
  for (const curve of curves.value) {
    if (!pendingLen(curve)) {
      curve.dripBatch = 0
      continue
    }
    const taken = takeLiveDrip(curve.pending, curve.pendingHead || 0)
    curve.pending = rawPoints(taken.buf)
    curve.pendingHead = taken.head
    const chunk = taken.chunk
    if (!chunk.length) continue
    curve.points = rawPoints(mergePoints(curve.points, chunk, CURVE_DISPLAY_MAX))
    changed = true
  }
  if (!changed) return
  paintLiveChart()
}

function startDrip() {
  if (dripTimer) return
  dripTimer = setInterval(dripPending, CURVE_DRIP_INTERVAL_MS)
}

function stopDrip() {
  if (!dripTimer) return
  clearInterval(dripTimer)
  dripTimer = null
}

/** 恢复自动刷新：暂停期间攒的点立刻上屏，不等滴灌。 */
function flushPauseCache() {
  let changed = false
  for (const curve of curves.value) {
    const parked = curve.pauseCache
    if (!parked?.length) continue
    curve.pauseCache = rawPoints([])
    curve.points = rawPoints(mergePoints(curve.points, parked, CURVE_DISPLAY_MAX))
    advanceCursor(curve)
    changed = true
  }
  startDrip()
  if (!changed) return
  paintLiveChart()
}

function parkPendingOnPause() {
  for (const curve of curves.value) {
    if (!pendingLen(curve)) continue
    curve.pauseCache = rawPoints(mergePoints(curve.pauseCache, pendingLive(curve), CURVE_PAUSE_CACHE_MAX))
    curve.pending = rawPoints([])
    curve.pendingHead = 0
    curve.dripBatch = 0
  }
}

/** 按起始时间清空并重新拉全量 */
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
  tsChart.value?.exitCropMode({ silent: true })
  querying.value = true
  pollGen += 1
  stopPoll()
  try {
    globalClearedAt.value = startMs
    for (const curve of curves.value) {
      curve.points = rawPoints([])
      curve.pauseCache = rawPoints([])
      curve.pending = rawPoints([])
      curve.pendingHead = 0
      curve.dripBatch = 0
      curve.fetchCursorT = startMs
      curve.sentSinceT = startMs
      curve.baselineT = startMs
      curve.cursorT = startMs
    }
    const rows = await fetchCurvesBatch(curves.value, { initial: true })
    applyBatchRows(rows, { forceToPoints: true, replace: true })
    tsChart.value?.resetTimeWindow()
    // 保留用户选择的起始时间，不用图表窗口（最早数据点）覆盖
    ElMessage.success('已按起始时间重新查询')
  } catch {
    ElMessage.error('查询失败，请稍后重试')
  } finally {
    querying.value = false
    if (curves.value.length) startPoll()
  }
}

function exportCurveCsv() {
  exportChartWindowCsv({
    tsChart: tsChart.value,
    curves: curves.value,
    filenamePrefix: 'telemetry-curve',
    pointsFor: c => mergePoints(c.points, pendingLive(c), CURVE_DISPLAY_MAX)
  })
}

function onCurveAction() {
  if (isCurrentOnChart.value) removeCurve(currentCurveKey.value)
  else addCurve()
}

function tableLabel(type) {
  const hit = tmPages.value.find(p => p.key === type)
  if (!hit) return type || ''
  const id = hit.localKey || hit.id || hit.key || type
  const name = hit.name ? String(hit.name) : ''
  return name ? `${id} ${name}` : String(id)
}

/** 图上已有其他表的曲线时，换表需先清空 */
function needsTableSwitch(type) {
  if (!curves.value.length) return false
  return curves.value.some(c => c.tmType !== type)
}

/** 换表确认：清空旧表曲线后再加新曲线 */
async function confirmSwitchTable(nextType) {
  const oldType = curves.value[0]?.tmType || ''
  try {
    await ElMessageBox.confirm(
      `遥测表已更换为「${tableLabel(nextType)}」，图上「${tableLabel(oldType)}」的曲线和数据将被清空。是否继续？`,
      '更换遥测表',
      {
        type: 'warning',
        confirmButtonText: '清空并添加',
        cancelButtonText: '取消'
      }
    )
    return true
  } catch {
    return false
  }
}

/** 清空全部曲线并退出截取模式（换表前调用） */
function clearAllCurves() {
  for (const c of curves.value) releaseColor(c.key)
  curves.value = []
  holdDrip = false
  stopPoll()
  tsChart.value?.exitCropMode({ silent: true })
}

/** 增加当前选中遥测量；本页点「增加曲线」跨表时先确认。从遥测表带参跳入不弹窗，直接清旧图。 */
async function addCurve({ skipSwitchConfirm = false } = {}) {
  if (isCurrentOnChart.value) return
  if (!field.value) {
    ElMessage.warning('请选择遥测量')
    return
  }
  if (needsTableSwitch(tmType.value)) {
    if (!skipSwitchConfirm) {
      const ok = await confirmSwitchTable(tmType.value)
      if (!ok) return
    }
    clearAllCurves()
  }
  if (curves.value.length >= MAX_CURVES) {
    ElMessage.warning(`最多同时显示 ${MAX_CURVES} 条曲线（颜色数量上限）`)
    return
  }
  const key = curveKey(tmType.value, field.value)
  const hadOthers = curves.value.length > 0
  adding.value = true
  pollGen += 1
  if (hadOthers) holdDrip = true
  try {
    const stub = {
      key,
      tmType: tmType.value,
      field: field.value,
      name: '',
      unit: '',
      color: acquireColor(key),
      points: rawPoints([]),
      pending: rawPoints([]),
      pendingHead: 0,
      dripBatch: 0,
      pauseCache: rawPoints([]),
      baselineT: globalClearedAt.value ?? null,
      cursorT: globalClearedAt.value ?? null,
      fetchCursorT: globalClearedAt.value ?? null,
      sentSinceT: globalClearedAt.value ?? null
    }
    const toFetch = [...curves.value, stub]
    const rows = await fetchCurvesBatch(toFetch, { initialKeys: new Set([key]) })
    curves.value.push(stub)
    applyBatchRows(rows, { forceToPoints: true })
    if (hadOthers) flushDripBuffers()
    tsChart.value?.render()
    tsChart.value?.scheduleResize()
    nextTick(() => syncQueryStartFromChart({ force: !queryStartAt.value }))
  } finally {
    adding.value = false
    if (curves.value.length) startPoll()
  }
}

/** 从图上移除一条曲线并释放色号 */
function removeCurve(key) {
  const curve = curves.value.find(c => c.key === key)
  if (!curve) return
  releaseColor(key)
  curves.value = curves.value.filter(c => c.key !== key)
  if (!curves.value.length) {
    holdDrip = false
    stopPoll()
    tsChart.value?.exitCropMode({ silent: true })
  } else if (curves.value.length < 2) {
    holdDrip = false
  }
  tsChart.value?.render({ full: true })
}

/** 换表只刷新遥测量列表，不自动清图；清掉双击带入的 URL 参数，刷新不再被旧 type 打回 */
function onTypeChange() {
  loadFields()
  if (route.query.from == null && route.query.type == null && route.query.field == null && route.query.family == null) {
    return
  }
  const next = { ...route.query }
  delete next.from
  delete next.type
  delete next.field
  delete next.family
  router.replace({ query: next })
}

/** 从遥测表页双击跳转：带 type/field/from=table */
function shouldAutoAdd() {
  return route.query.from === 'table' && !!route.query.field
}

/** 按路由参数选表/字段并加曲线。从遥测表双击进入：表不同也直接清旧数据，不弹确认。 */
async function applyRouteAndAdd() {
  if (!shouldAutoAdd()) return
  if (route.query.type) {
    const qType = String(route.query.type).toUpperCase()
    const qFam = route.query.family ? String(route.query.family).toLowerCase() : ''
    const hit =
      tmPages.value.find(p => p.key === qType && (!qFam || p.family === qFam)) ||
      tmPages.value.find(p => p.key === qType)
    if (hit) tmSelect.value = hit.key
  }
  field.value = String(route.query.field)
  await loadFields()
  if (!field.value || isCurrentOnChart.value) return
  await addCurve({ skipSwitchConfirm: true })
}

async function bootstrap() {
  await loadPages()
  await loadFields()
  if (shouldAutoAdd()) await applyRouteAndAdd()
  else tsChart.value?.scheduleResize()
  nextTick(() => syncQueryStartFromChart({ force: !queryStartAt.value }))
}

watch(autoRefresh, val => {
  if (val) {
    flushPauseCache()
  } else {
    parkPendingOnPause()
  }
})

watch(downsampleRatio, () => writeCurvePrefs())

watch([tmSelect, field], writeCurvePrefs)

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
  startDrip()
  await bootstrap()
})

onActivated(async () => {
  if (shouldAutoAdd()) {
    const nextKey = curveKey(
      String(route.query.type || tmType.value).toUpperCase(),
      String(route.query.field)
    )
    if (!curves.value.some(c => c.key === nextKey)) {
      // keep-alive 再次进入（含从别的遥测表双击跳回）：直接清旧图加新曲线
      await applyRouteAndAdd()
    }
  }
  if (curves.value.length) {
    await tick()
    startPoll()
  }
  startDrip()
  tsChart.value?.scheduleResize()
})

onDeactivated(() => {
  tsChart.value?.exitCropMode({ silent: true })
  stopPoll()
  stopDrip()
})

onBeforeUnmount(() => {
  stopPoll()
  stopDrip()
})

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    pollGen += 1
    stopPoll()
    stopDrip()
  })
}
</script>

<style scoped>
.curve-page {
  padding: 12px 16px 12px 10px !important;
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
  margin-right: 20px;
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
.curve-fps {
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
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
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color);
  color: var(--el-text-color-secondary);
  font-size: 13px;
  pointer-events: none;
}
.action-btn {
  min-width: 88px;
}
</style>
