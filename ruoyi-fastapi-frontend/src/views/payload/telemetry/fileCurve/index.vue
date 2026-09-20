<template>
  <div class="app-container curve-page">
    <div class="toolbar-row">
      <TelemetryFileToolbar
        class="toolbar"
        v-model:file-path="filePath"
        v-model:tm-type="tmSelect"
        :parsing="parsing"
        channel="curve"
        @parse="onParse"
        @type-change="onTypeChange"
      />
      <CurveChartTools
        :crop-mode="cropMode"
        :disabled="!curves.length"
        crop-tip="截取片段（拖选）"
        export-tip="导出当前窗口为 CSV"
        @crop="onToggleCrop"
        @export="exportCurveCsv"
      />
    </div>

    <el-form :inline="true" label-width="70px" class="toolbar-options">
      <el-form-item label="遥测量">
        <el-select v-model="field" filterable style="width: 280px">
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
      <el-form-item class="range-item">
        <div class="range-slider">
          <el-tooltip content="块序号半开区间。选 0 和 2 表示第 0、1 块（共 2 万帧），不含第 2 块。" placement="top">
            <span class="slider-edge slider-edge-range">{{ displayRangeLabel }}</span>
          </el-tooltip>
            <div class="slider-track">
              <el-slider
                v-model="indexRange"
                range
                :min="0"
                :max="sliderMax"
                :disabled="!frameCount"
                @change="onRangeUserChange"
              />
            </div>
            <span class="slider-edge slider-edge-total">{{ sliderMax }}</span>
        </div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" class="action-btn" :disabled="!curves.length" :loading="querying" @click="queryCurves">
          查询
        </el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置曲线</el-button>
      </el-form-item>
    </el-form>

    <CurveLegend :curves="curves" @remove="removeCurve" />

    <div class="chart-wrap">
      <div v-if="!curves.length" class="empty-hint">请先解析文件，选择遥测量后点击「增加曲线」</div>
      <TimeSeriesChart
        ref="tsChart"
        :get-series="getChartSeries"
        :get-series-points="getChartPoints"
        :show-controls="curves.length > 0"
      />
    </div>
  </div>
</template>

<script setup name="Filecurve">
/**
 * 历史文件曲线。组件名 Filecurve 对齐路由 name=path.capitalize()，才能进 keep-alive。
 */
import { ElMessage } from 'element-plus'
import TelemetryFileToolbar from '@/components/Payload/TelemetryFileToolbar.vue'
import { getTelemetryFields } from '@/api/payload/telemetry'
import { decideFileParseAction, getTelemetryFileCurve, getTelemetryFileStatus, startFileParsePoll } from '@/api/payload/telemetry'
import { CurveChartTools, CurveLegend, TimeSeriesChart } from '@/components/TimeSeriesChart'
import cache from '@/plugins/cache'
import { exportChartWindowCsv, MAX_CURVES, curveKey, normalizePoints, useCurveChartPage } from '@/utils/curvePage'

const PREFS_KEY = 'payload:fileCurve:prefs:v1'
const PARSE_TIMEOUT_MS = 60000
const CURVE_CHUNK = 10000
const POLL_MS = 400

function writePrefs() {
  cache.local.setJSON(PREFS_KEY, {
    tmSelect: tmSelect.value || '',
    filePath: filePath.value || '',
    field: field.value || ''
  })
}

const prefs = cache.local.getJSON(PREFS_KEY, {}) || {}

const tsChart = ref(null)

const filePath = ref(String(prefs.filePath || ''))
const tmSelect = ref(String(prefs.tmSelect || ''))
const parsing = ref(false)
const field = ref(String(prefs.field || ''))
const fields = ref([])
const curves = ref([])
const adding = ref(false)
const querying = ref(false)
const parsed = ref(false)
const pathHash = ref('')
const frameCount = ref(0)
const indexRange = ref([0, 1])
let parseJob = null
let scanActive = false
let lastParseKey = ''
let rangeManual = false
let fetchGen = 0

function currentParseKey() {
  return `${String(tmSelect.value || '').toUpperCase()}|${filePath.value || ''}`
}

const sliderMax = computed(() => {
  const n = Number(frameCount.value) || 0
  return n > 0 ? Math.ceil(n / CURVE_CHUNK) : 0
})
const displayRangeStart = computed(() => Number(indexRange.value[0]) || 0)
const displayRangeEnd = computed(() => Number(indexRange.value[1]) || displayRangeStart.value)
const displayRangeLabel = computed(() => `${displayRangeStart.value}~${displayRangeEnd.value}`)

function applyDefaultRange() {
  const max = sliderMax.value
  if (!rangeManual) {
    indexRange.value = [0, max ? Math.min(1, max) : 0]
    return
  }
  if (!max) {
    indexRange.value = [0, 0]
    return
  }
  let a = Math.min(Math.max(0, Number(indexRange.value[0]) || 0), max)
  let b = Math.min(Math.max(a, Number(indexRange.value[1]) || a), max)
  indexRange.value = [a, b]
}

function onRangeUserChange() {
  rangeManual = true
}

function currentRange() {
  const max = sliderMax.value
  let a = Math.max(0, Number(indexRange.value[0]) || 0)
  let b = Math.max(a, Number(indexRange.value[1]) || a)
  if (max) {
    a = Math.min(a, max)
    b = Math.min(b, max)
  }
  return { startIndex: a, endIndex: b }
}
const { acquireColor, releaseColor, cropMode, getChartSeries, getChartPoints, onToggleCrop } = useCurveChartPage(
  tsChart,
  curves
)

const tmType = computed(() => String(tmSelect.value || '').toUpperCase())
const tmFamily = computed(() => {
  const s = tmType.value
  const i = s.indexOf(':')
  if (i > 0) return s.slice(0, i).toLowerCase()
  return ''
})

const currentCurveKey = computed(() => (field.value ? curveKey(tmType.value, field.value) : ''))
const isCurrentOnChart = computed(() => curves.value.some(c => c.key === currentCurveKey.value))
const curveActionDisabled = computed(() => !field.value || adding.value || !parsed.value)

async function loadFields() {
  if (!tmType.value) {
    fields.value = []
    return
  }
  const res = await getTelemetryFields(tmType.value, tmFamily.value || undefined)
  fields.value = res.data || []
  if (field.value && !fields.value.some(f => f.id === field.value)) {
    field.value = fields.value[0]?.id || ''
  } else if (!field.value && fields.value.length) {
    field.value = fields.value[0].id
  }
}

function onTypeChange() {
  loadFields()
}

watch(tmSelect, () => loadFields())
watch(filePath, () => {
  parsed.value = false
  pathHash.value = ''
  frameCount.value = 0
  rangeManual = false
  applyDefaultRange()
  for (const c of curves.value) releaseColor(c.key)
  curves.value = []
  parseJob?.stop()
  scanActive = false
  lastParseKey = ''
})

function applyExistingSession(data) {
  lastParseKey = currentParseKey()
  if (data?.pathHash) pathHash.value = data.pathHash
  frameCount.value = Number(data?.frameCount) || 0
  rangeManual = false
  applyDefaultRange()
  parsed.value = true
  ElMessage.success(`已使用现有解析，当前 ${frameCount.value} 帧`)
}

async function onParse() {
  if (!filePath.value || !tmSelect.value) {
    ElMessage.warning('请选择遥测表和文件')
    return
  }
  const key = currentParseKey()
  if (scanActive && lastParseKey === key) {
    ElMessage.info('正在解析中')
    return
  }
  let force = 0
  let existing = null
  try {
    const res = await getTelemetryFileStatus({ path: filePath.value, channel: 'curve' })
    const action = decideFileParseAction(res.data, tmSelect.value)
    if (action === 'use' || action === 'confirm') {
      applyExistingSession(res.data)
      return
    }
    existing = res.data || null
  } catch {
    // 状态查不到时按新文件直接解析
  }
  parsing.value = true
  rangeManual = false
  frameCount.value = Number(existing?.frameCount) || 0
  applyDefaultRange()
  parseJob?.stop()
  scanActive = true
  lastParseKey = key
  const job = startFileParsePoll({
    type: tmSelect.value,
    path: filePath.value,
    channel: 'curve',
    timeoutMs: PARSE_TIMEOUT_MS,
    force,
    onProgress(data) {
      if (data.pathHash) pathHash.value = data.pathHash
      if (data.frameCount) {
        frameCount.value = Number(data.frameCount) || frameCount.value
        applyDefaultRange()
      }
    }
  })
  parseJob = job
  try {
    const data = await job.promise
    if (data.pathHash) pathHash.value = data.pathHash
    if (data.frameCount) {
      frameCount.value = Number(data.frameCount) || frameCount.value
      applyDefaultRange()
    }
    parsed.value = true
    ElMessage.success('已找到匹配帧，可增加曲线')
  } catch (e) {
    parsed.value = false
    if (lastParseKey === key) scanActive = false
    if (e?.message !== '已取消解析') ElMessage.error(e?.message || '解析失败')
  } finally {
    parsing.value = false
  }
  job.done.finally(() => {
    if (lastParseKey === key) scanActive = false
  })
}

async function onCurveAction() {
  if (isCurrentOnChart.value) {
    removeCurve(currentCurveKey.value)
    return
  }
  if (curves.value.length >= MAX_CURVES) {
    ElMessage.warning(`最多 ${MAX_CURVES} 条曲线`)
    return
  }
  const f = fields.value.find(x => x.id === field.value)
  const key = currentCurveKey.value
  curves.value.push({
    key,
    tmType: tmType.value,
    field: field.value,
    name: f?.name || field.value,
    unit: f?.unit || '',
    color: acquireColor(key),
    points: [],
    chunkMap: {}
  })
  tsChart.value?.render()
  tsChart.value?.scheduleResize()
  const { startIndex, endIndex } = currentRange()
  const toFetch = curves.value.filter(c => c.loadedStart !== startIndex || c.loadedEnd !== endIndex)
  adding.value = true
  try {
    await fetchCurves(toFetch, { toast: false })
  } finally {
    adding.value = false
  }
}

function removeCurve(key) {
  curves.value = curves.value.filter(c => c.key !== key)
  releaseColor(key)
  tsChart.value?.render()
  tsChart.value?.scheduleResize()
}

function haveChunksOf(curve, start, end) {
  const map = curve.chunkMap || {}
  const out = []
  for (let c = start; c < end; c++) {
    if (Object.prototype.hasOwnProperty.call(map, c)) out.push(c)
  }
  return out
}

function neededChunks(start, end) {
  const out = []
  for (let c = start; c < end; c++) out.push(c)
  return out
}

function allChunksLocal(list, start, end) {
  const need = neededChunks(start, end)
  if (!need.length) return true
  return list.every(c => {
    const have = new Set(haveChunksOf(c, start, end))
    return need.every(n => have.has(n))
  })
}

function flattenChunkMap(map, start, end) {
  const out = []
  for (let c = start; c < end; c++) {
    const pts = map[c]
    if (Array.isArray(pts) && pts.length) out.push(...pts)
  }
  return out
}

async function fetchCurves(list, { toast = true } = {}) {
  if (!list.length) return true
  if (!parsed.value) {
    ElMessage.warning('请先解析文件')
    return false
  }
  if (!pathHash.value) {
    ElMessage.warning('请先解析文件')
    return false
  }
  const { startIndex, endIndex } = currentRange()
  if (allChunksLocal(list, startIndex, endIndex)) {
    for (const c of list) {
      if (!c.chunkMap) c.chunkMap = {}
      c.points = flattenChunkMap(c.chunkMap, startIndex, endIndex)
      c.loadedStart = startIndex
      c.loadedEnd = endIndex
    }
    tsChart.value?.render()
    return true
  }
  const gen = ++fetchGen
  const deadline = Date.now() + PARSE_TIMEOUT_MS
  let anyPoints = false
  let pending = []
  let firstPaint = true
  try {
    while (Date.now() < deadline) {
      if (gen !== fetchGen) return false
      if (allChunksLocal(list, startIndex, endIndex)) {
        pending = []
        break
      }
      const res = await getTelemetryFileCurve({
        pathHash: pathHash.value,
        channel: 'curve',
        items: list.map(c => ({
          type: c.tmType,
          field: c.field,
          haveChunks: haveChunksOf(c, startIndex, endIndex)
        })),
        startIndex,
        endIndex
      })
      if (gen !== fetchGen) return false
      const payload = res.data || {}
      if (payload.error) {
        ElMessage.error(payload.error)
        return false
      }
      if (payload.sessionGone) {
        ElMessage.error('该文件会话已失效，请重新解析')
        return false
      }
      if (payload.frameCount) {
        frameCount.value = Number(payload.frameCount) || frameCount.value
        applyDefaultRange()
      }
      const rows = payload.items || payload
      const rowList = Array.isArray(rows) ? rows : []
      anyPoints = false
      for (const row of rowList) {
        const type = String(row.type || '').toUpperCase()
        const found = curves.value.find(c => c.key === curveKey(type, row.field)) || curves.value.find(c => c.field === row.field)
        if (!found) continue
        if (row.name && String(row.name) !== String(found.field)) found.name = row.name
        if (row.unit) found.unit = row.unit
        if (!found.chunkMap) found.chunkMap = {}
        const incoming = row.chunkPoints || {}
        for (const [ck, pts] of Object.entries(incoming)) {
          found.chunkMap[Number(ck)] = normalizePoints(pts)
        }
        found.points = flattenChunkMap(found.chunkMap, startIndex, endIndex)
        found.loadedStart = startIndex
        found.loadedEnd = endIndex
        if (found.points.length) anyPoints = true
      }
      if (firstPaint) {
        tsChart.value?.resetTimeWindow()
        firstPaint = false
      }
      tsChart.value?.render()
      pending = Array.isArray(payload.pendingChunks) ? payload.pendingChunks : []
      if (!pending.length) break
      await new Promise(r => setTimeout(r, POLL_MS))
    }
    if (gen !== fetchGen) return false
    if (toast) {
      if (pending.length) ElMessage.warning('部分曲线块仍在解析，可稍后查询')
      else if (!anyPoints) ElMessage.warning('暂无曲线数据')
      else ElMessage.success('已加载文件曲线')
    }
    return !pending.length
  } catch (e) {
    return false
  }
}

async function queryCurves() {
  if (!curves.value.length) {
    ElMessage.warning('请先增加曲线')
    return
  }
  if (!parsed.value) {
    ElMessage.warning('请先解析文件')
    return
  }
  querying.value = true
  try {
    await fetchCurves(curves.value, { toast: true })
  } finally {
    querying.value = false
  }
}

function onResetTimeWindow() {
  tsChart.value?.resetTimeWindow()
}

function exportCurveCsv() {
  exportChartWindowCsv({
    tsChart: tsChart.value,
    curves: curves.value,
    filenamePrefix: 'telemetry-file'
  })
}

watch(
  () => curves.value.map(c => c.key).join('|'),
  () => tsChart.value?.render()
)
watch([tmSelect, filePath, field], writePrefs)

onMounted(() => {
  tsChart.value?.scheduleResize()
  loadFields()
})

onBeforeUnmount(() => {
  parseJob?.stop()
})
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
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.toolbar-options :deep(.el-form-item) {
  margin-bottom: 4px;
  margin-right: 20px;
}
.range-item {
  flex: 1 1 280px;
  min-width: 280px;
  margin-right: 12px !important;
}
.range-item :deep(.el-form-item__content) {
  margin-left: 0 !important;
  width: 100%;
}
.range-slider {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  min-width: 0;
}
.slider-track {
  position: relative;
  flex: 1;
  min-width: 0;
}
.slider-track :deep(.el-slider) {
  width: 100%;
}
.slider-track :deep(.el-slider__button-wrapper) {
  z-index: 2;
}
.slider-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 1;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--el-text-color-secondary);
  text-shadow: 0 0 6px var(--el-bg-color), 0 0 6px var(--el-bg-color);
  white-space: nowrap;
}
.slider-edge {
  flex-shrink: 0;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  overflow: hidden;
}
.slider-edge-range {
  width: 8ch;
  min-width: 8ch;
  text-align: right;
}
.slider-edge-total {
  width: 6ch;
  min-width: 6ch;
  text-align: left;
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
