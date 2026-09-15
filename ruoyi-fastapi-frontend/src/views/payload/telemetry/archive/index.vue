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
      <el-form-item label="结束时间">
        <el-date-picker
          v-model="queryEndAt"
          type="datetime"
          placeholder="选择结束时间"
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
          @click="queryFromTimeRange"
        >
          查询
        </el-button>
      </el-form-item>
      <el-form-item>
        <el-button class="action-btn" :disabled="!curves.length" @click="onResetTimeWindow">重置曲线</el-button>
      </el-form-item>
    </el-form>

    <CurveLegend :curves="curves" @remove="removeCurve" />

    <div class="chart-wrap">
      <div v-if="!curves.length" class="empty-hint">请选择遥测量后点击「增加曲线」，再选择时间区间查询</div>
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

<script setup name="TelemetryArchive">
import { ElMessage } from 'element-plus'
import cache from '@/plugins/cache'
import { loadTelemetryPagesCached } from '@/utils/telemetryPages'
import { getTelemetryFields, getTelemetryHistoryCurveDataBatch } from '@/api/payload/telemetry'
import { CurveChartTools, CurveLegend, TimeSeriesChart } from '@/components/TimeSeriesChart'
import { exportChartWindowCsv, MAX_CURVES, curveKey, normalizePoints, useCurveChartPage } from '@/utils/curvePage'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

const CURVE_FETCH_LIMIT = 50000
const DEFAULT_RANGE_MS = 10 * 60 * 1000
const DEFAULT_VIEW_WINDOW_MS = 10 * 60 * 1000

const ARCHIVE_PREFS_KEY = 'payload:archive:prefs:v1'

function writeArchivePrefs() {
  cache.local.setJSON(ARCHIVE_PREFS_KEY, {
    tmSelect: tmSelect.value || '',
    field: field.value || '',
    queryStartAt: queryStartAt.value || '',
    queryEndAt: queryEndAt.value || ''
  })
}

const archivePrefs = cache.local.getJSON(ARCHIVE_PREFS_KEY, {}) || {}

const route = useRoute()
const tsChart = ref(null)

const tmPages = ref([])
const tmSelect = ref('') // 存储键 BIU:FF / XL:FF
const field = ref(
  route.query.field ? String(route.query.field) : String(archivePrefs.field || '')
)
const fields = ref([])
const curves = ref([])
const adding = ref(false)
const queryStartAt = ref('')
const queryEndAt = ref('')
const querying = ref(false)
const queryRange = ref({ startT: null, endT: null })
const { acquireColor, releaseColor, cropMode, getChartSeries, getChartPoints, onToggleCrop } = useCurveChartPage(
  tsChart,
  curves
)

const tmType = computed(() => String(tmSelect.value || '').toUpperCase())
const tmFamily = computed(() => {
  const hit = tmPages.value.find(p => p.key === tmSelect.value || p.key === tmType.value)
  if (hit?.family) return String(hit.family).toLowerCase()
  const s = tmType.value
  const i = s.indexOf(':')
  if (i > 0) return s.slice(0, i).toLowerCase()
  return 'biu'
})

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
  const cachedStart = parseDateTimeMs(archivePrefs.queryStartAt)
  const cachedEnd = parseDateTimeMs(archivePrefs.queryEndAt)
  if (
    Number.isFinite(cachedStart) &&
    cachedStart > 0 &&
    Number.isFinite(cachedEnd) &&
    cachedEnd > 0 &&
    cachedStart <= cachedEnd
  ) {
    queryStartAt.value = archivePrefs.queryStartAt
    queryEndAt.value = archivePrefs.queryEndAt
    queryRange.value = { startT: cachedStart, endT: cachedEnd }
    return
  }
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
  const win = tsChart.value?.getTimeWindow()
  let start = win?.start
  if (start == null || !Number.isFinite(Number(start)) || Number(start) <= 0) {
    start = tsChart.value?.getEarliestTime() || Date.now() - DEFAULT_RANGE_MS
  }
  start = Number(start)
  if (!Number.isFinite(start) || start < 946684800000) {
    start = Date.now() - DEFAULT_RANGE_MS
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

function onResetTimeWindow() {
  tsChart.value?.resetTimeWindow()
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

function onChartViewChange() {
  nextTick(() => syncQueryStartFromChart({ force: true }))
}

async function loadPages() {
  tmPages.value = (await loadTelemetryPagesCached()).filter(p => p.key)
  const qType = route.query.type ? String(route.query.type).toUpperCase() : ''
  const qFam = route.query.family ? String(route.query.family).toLowerCase() : ''
  let hit = null
  if (qType) {
    hit =
      tmPages.value.find(p => p.key === qType) ||
      tmPages.value.find(
        p => (p.localKey || p.id) === qType && (!qFam || p.family === qFam)
      ) ||
      tmPages.value.find(p => (p.localKey || p.id) === qType)
  }
  if (!hit && archivePrefs.tmSelect) {
    hit = tmPages.value.find(p => p.key === archivePrefs.tmSelect)
  }
  if (!hit) hit = tmPages.value[0]
  if (hit) tmSelect.value = hit.key
}

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

function buildBatchItem(curve) {
  const range = queryRange.value
  return {
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
    const key = curveKey(type, row.field)
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
  tsChart.value?.exitCropMode({ silent: true })
  querying.value = true
  try {
    queryRange.value = range
    for (const curve of curves.value) {
      curve.points = []
    }
    const rows = await fetchCurvesBatch(curves.value)
    applyBatchRows(rows)
    tsChart.value?.resetTimeWindow()
    // 保留用户选择的起止时间，不用图表窗口（最早数据点）覆盖
    ElMessage.success('已按时间区间加载归档数据')
  } catch {
    ElMessage.error('查询失败，请稍后重试')
  } finally {
    querying.value = false
  }
}

function exportCurveCsv() {
  exportChartWindowCsv({
    tsChart: tsChart.value,
    curves: curves.value,
    filenamePrefix: 'telemetry-archive'
  })
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
    tsChart.value?.render()
    tsChart.value?.scheduleResize()
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
    tsChart.value?.exitCropMode({ silent: true })
  }
  tsChart.value?.render({ full: true })
}

function onTypeChange() {
  loadFields()
}

async function bootstrap() {
  initDefaultTimeRange()
  await loadPages()
  await loadFields()
  tsChart.value?.scheduleResize()
}

watch([tmSelect, field, queryStartAt, queryEndAt], writeArchivePrefs)

onMounted(async () => {
  await bootstrap()
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
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.toolbar-options :deep(.el-form-item) {
  margin-bottom: 4px;
  margin-right: 20px;
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
