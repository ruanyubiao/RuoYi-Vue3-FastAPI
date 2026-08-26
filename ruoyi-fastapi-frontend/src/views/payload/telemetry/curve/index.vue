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
        <el-button class="action-btn" :disabled="!curves.length" @click="onFollowLatest">跟随最新</el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="onFitYAxis">坐标轴自适应</el-button>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'
import { getTelemetryCurveDataBatch, getTelemetryFields } from '@/api/payload/telemetry'
import { useTimeSeriesChart } from '@/components/TimeSeriesChart'
import { buildAlignedSeriesTable, exportCsvFile, formatCsvDateTime } from '@/utils/csvExport'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

/** 首次/查询拉取上限 */
const CURVE_FETCH_LIMIT = 50000
/** 增量轮询每条曲线点数 */
const CURVE_INCREMENT_LIMIT = 500
const CURVE_DISPLAY_MAX = 50000
/** 暂停自动刷新时暂存的增量点数 */
const CURVE_PAUSE_CACHE_MAX = 1000
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000
const POLL_INTERVAL_MS = 1000
/** 同时曲线数上限（与颜色池长度一致） */
const MAX_CURVES = 10

const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]

const CURVE_PREFS_KEY = 'payload:curve:prefs:v1'

function readCurvePrefs() {
  try {
    const raw = localStorage.getItem(CURVE_PREFS_KEY)
    if (!raw) return null
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : null
  } catch {
    return null
  }
}

function writeCurvePrefs() {
  try {
    localStorage.setItem(
      CURVE_PREFS_KEY,
      JSON.stringify({
        tmSelect: tmSelect.value || '',
        field: field.value || '',
        autoRefresh: !!autoRefresh.value,
        zoomX: !!zoomX.value,
        zoomY: !!zoomY.value
      })
    )
  } catch {
    /* quota */
  }
}

const curvePrefs = readCurvePrefs() || {}

const route = useRoute()
const chartRef = ref(null)
let pollTimer = null
let tickBusy = false
const keyColorIdx = {}
/** 当前图上已占用的色号 */
const activeColorIndices = new Set()
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
const autoRefresh = ref(typeof curvePrefs.autoRefresh === 'boolean' ? curvePrefs.autoRefresh : true)
const zoomX = ref(typeof curvePrefs.zoomX === 'boolean' ? curvePrefs.zoomX : true)
const zoomY = ref(typeof curvePrefs.zoomY === 'boolean' ? curvePrefs.zoomY : false)
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

/** 曲线唯一键：表类型:字段 */
function curveKey(type, fld) {
  return `${type}:${fld}`
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

function onFollowLatest() {
  tsChart.followLatest()
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

function onResetTimeWindow() {
  tsChart.resetTimeWindow()
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

function onFitYAxis() {
  tsChart.fitYAxis()
}

/**
 * 颜色池：activeColorIndices = 当前图上已占用的色号。
 * 删除只释放占用；key→色号偏好可保留。再添加时若偏好色已被占用则改分空闲色，避免重复。
 */
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
  if (sinceT != null) item.sinceT = sinceT
  return item
}

async function fetchCurvesBatch(curveList, { initial = false } = {}) {
  if (!curveList.length) return []
  const items = curveList.map(c => buildBatchItem(c, { initial }))
  const res = await getTelemetryCurveDataBatch(items)
  return res.data || []
}

/** 把 batch 行写入对应曲线；暂停刷新时进 pauseCache */
function applyBatchRows(rows, { forceToPoints = false, replace = false } = {}) {
  for (const row of rows) {
    const type = String(row.type || '').toUpperCase()
    const key = curveKey(type, row.field)
    const curve =
      curves.value.find(c => c.key === key) ||
      curves.value.find(c => c.tmType === type && c.field === row.field)
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

/** 轮询增量点；自动刷新开启时才刷图 */
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

/** 恢复自动刷新：把 pauseCache 合并进 points */
function flushPauseCache() {
  for (const curve of curves.value) {
    if (!curve.pauseCache?.length) continue
    curve.points = mergePoints(curve.points, curve.pauseCache, CURVE_DISPLAY_MAX)
    curve.pauseCache = []
    advanceCursor(curve)
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
    // 保留用户选择的起始时间，不用图表窗口（最早数据点）覆盖
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
  stopPoll()
  tsChart.exitCropMode({ silent: true })
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
  adding.value = true
  try {
    const stub = {
      key,
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
    startPoll()
    tsChart.render()
    tsChart.scheduleResize()
    nextTick(() => syncQueryStartFromChart({ force: !queryStartAt.value }))
  } finally {
    adding.value = false
  }
}

/** 从图上移除一条曲线并释放色号 */
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

/** 换表只刷新遥测量列表，不自动清图（点「增加曲线」时才确认） */
function onTypeChange() {
  loadFields()
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

watch([tmSelect, field, autoRefresh, zoomX, zoomY], writeCurvePrefs)

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
  margin-right: 20px;
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
