<template>
  <div class="app-container curve-page">
    <TelemetryFileToolbar
      v-model:file-path="filePath"
      v-model:tm-type="tmSelect"
      :parsing="parsing"
      @parse="onParse"
      @type-change="onTypeChange"
    />

    <div class="toolbar-row">
      <el-form :inline="true" label-width="70px" class="toolbar">
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
        <el-form-item>
          <el-button type="primary" class="action-btn" :disabled="!curves.length" :loading="querying" @click="queryCurves">
            查询
          </el-button>
        </el-form-item>
        <el-form-item>
          <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置曲线</el-button>
        </el-form-item>
        <el-form-item>
          <el-button class="action-btn" :disabled="!curves.length" @click="onFitYAxis">坐标轴自适应</el-button>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="zoomX">X轴缩放</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="zoomY">Y轴缩放</el-checkbox>
        </el-form-item>
      </el-form>
      <div class="icon-tool-group">
        <el-tooltip :content="cropMode ? '再次点击取消截取' : '截取片段（拖选）'" placement="top">
          <span class="icon-tool-wrap">
            <el-button class="icon-tool-btn" :type="cropMode ? 'primary' : 'default'" :disabled="!curves.length" @click="onToggleCrop">
              <el-icon><Crop /></el-icon>
            </el-button>
          </span>
        </el-tooltip>
        <el-tooltip content="导出当前窗口为 CSV" placement="top">
          <span class="icon-tool-wrap">
            <el-button class="icon-tool-btn" :disabled="!curves.length" @click="exportCurveCsv">
              <el-icon><Download /></el-icon>
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

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
      <div v-if="!curves.length" class="empty-hint">请先解析文件，选择遥测量后点击「增加曲线」，再查询</div>
      <div ref="chartRef" class="chart-box" />
    </div>
  </div>
</template>

<script setup name="Filecurve">
/**
 * 历史文件曲线。组件名 Filecurve 对齐路由 name=path.capitalize()，才能进 keep-alive。
 */
import { Close, Crop, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import TelemetryFileToolbar from '@/components/Payload/TelemetryFileToolbar.vue'
import { getTelemetryFields } from '@/api/payload/telemetry'
import { getTelemetryFileCurve, startFileParsePoll } from '@/api/payload/telemetry'
import { useTimeSeriesChart } from '@/components/TimeSeriesChart'
import { buildAlignedSeriesTable, exportCsvFile, formatCsvDateTime } from '@/utils/csvExport'

const MAX_CURVES = 10
const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]
const PREFS_KEY = 'payload:fileCurve:prefs:v1'
const PARSE_TIMEOUT_MS = 60000

function readPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    const obj = raw ? JSON.parse(raw) : null
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

function writePrefs() {
  try {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        tmSelect: tmSelect.value || '',
        filePath: filePath.value || '',
        field: field.value || '',
        zoomX: !!zoomX.value,
        zoomY: !!zoomY.value
      })
    )
  } catch {
    /* quota */
  }
}

const prefs = readPrefs()

const chartRef = ref(null)
const keyColorIdx = {}
const activeColorIndices = new Set()

const filePath = ref(String(prefs.filePath || ''))
const tmSelect = ref(String(prefs.tmSelect || ''))
const parsing = ref(false)
const field = ref(String(prefs.field || ''))
const fields = ref([])
const curves = ref([])
const adding = ref(false)
const querying = ref(false)
const zoomX = ref(typeof prefs.zoomX === 'boolean' ? prefs.zoomX : true)
const zoomY = ref(typeof prefs.zoomY === 'boolean' ? prefs.zoomY : false)
const parsed = ref(false)
let parseJob = null

const tmType = computed(() => String(tmSelect.value || '').toUpperCase())
const tmFamily = computed(() => {
  const s = tmType.value
  const i = s.indexOf(':')
  if (i > 0) return s.slice(0, i).toLowerCase()
  return ''
})

function curveKey(type, fld) {
  return `${type}:${fld}`
}
const currentCurveKey = computed(() => (field.value ? curveKey(tmType.value, field.value) : ''))
const isCurrentOnChart = computed(() => curves.value.some(c => c.key === currentCurveKey.value))
const curveActionDisabled = computed(() => !field.value || adding.value || !parsed.value)

const tsChart = useTimeSeriesChart({
  chartRef,
  zoomX,
  zoomY,
  defaultViewWindowMs: 10 * 60 * 1000,
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

function acquireColor(key) {
  const prefer = keyColorIdx[key]
  if (prefer !== undefined && !activeColorIndices.has(prefer)) {
    activeColorIndices.add(prefer)
    return SERIES_COLORS[prefer]
  }
  let idx = 0
  while (idx < SERIES_COLORS.length && activeColorIndices.has(idx)) idx++
  if (idx >= SERIES_COLORS.length) idx = 0
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
})

async function onParse() {
  if (!filePath.value || !tmSelect.value) {
    ElMessage.warning('请选择遥测表和文件')
    return
  }
  parsing.value = true
  parseJob?.stop()
  const job = startFileParsePoll({
    type: tmSelect.value,
    path: filePath.value,
    timeoutMs: PARSE_TIMEOUT_MS
  })
  parseJob = job
  try {
    await job.promise
    parsed.value = true
    ElMessage.success('解析成功，可增加曲线后查询')
  } catch (e) {
    parsed.value = false
    if (e?.message !== '已取消解析') ElMessage.error(e?.message || '解析失败')
  } finally {
    if (parseJob === job) parseJob = null
    parsing.value = false
  }
}

function onCurveAction() {
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
    points: []
  })
  tsChart.render()
  tsChart.scheduleResize()
  queryCurves()
}

function removeCurve(key) {
  curves.value = curves.value.filter(c => c.key !== key)
  releaseColor(key)
  tsChart.render()
  tsChart.scheduleResize()
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
    const res = await getTelemetryFileCurve({
      path: filePath.value,
      items: curves.value.map(c => ({ type: c.tmType, field: c.field }))
    })
    const rows = res.data?.items || res.data || []
    const list = Array.isArray(rows) ? rows : []
    for (const row of list) {
      const type = String(row.type || '').toUpperCase()
      const key = curveKey(type, row.field)
      const curve = curves.value.find(c => c.key === key) || curves.value.find(c => c.field === row.field)
      if (!curve) continue
      curve.name = row.name || curve.field
      curve.unit = row.unit || ''
      curve.points = normalizePoints(row.points)
    }
    tsChart.resetTimeWindow()
    tsChart.render()
    ElMessage.success('已加载文件曲线')
  } catch (e) {
    ElMessage.error(e?.message || '查询失败')
  } finally {
    querying.value = false
  }
}

function onResetTimeWindow() {
  tsChart.resetTimeWindow()
}

function onFitYAxis() {
  tsChart.fitYAxis()
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
    ElMessage.warning('无法获取当前窗口')
    return
  }
  const seriesList = curves.value.map(c => ({
    name: `${c.field} ${c.name}${c.unit ? `(${c.unit})` : ''}`.trim(),
    points: c.points
  }))
  const { headers, rows } = buildAlignedSeriesTable(seriesList, win)
  if (!rows.length) {
    ElMessage.warning('当前窗口内无数据点可导出')
    return
  }
  const stamp = formatCsvDateTime(Date.now()).replace(/[: ]/g, '-').replace(/\./g, '_')
  exportCsvFile({ headers, rows, filename: `telemetry-file-${stamp}.csv` })
  ElMessage.success(`已导出 ${rows.length} 行`)
}

watch([zoomX, zoomY], () => tsChart.refreshZoomBindings())
watch(
  () => curves.value.map(c => c.key).join('|'),
  () => tsChart.render()
)
watch([tmSelect, filePath, field, zoomX, zoomY], writePrefs)

onMounted(() => {
  tsChart.init()
  tsChart.scheduleResize()
  window.addEventListener('resize', tsChart.resize)
  loadFields()
})

onBeforeUnmount(() => {
  parseJob?.stop()
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
