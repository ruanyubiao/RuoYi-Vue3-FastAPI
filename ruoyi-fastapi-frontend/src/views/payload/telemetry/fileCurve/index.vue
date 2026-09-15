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
      </el-form>
      <CurveChartTools
        :crop-mode="cropMode"
        :disabled="!curves.length"
        crop-tip="截取片段（拖选）"
        export-tip="导出当前窗口为 CSV"
        @crop="onToggleCrop"
        @export="exportCurveCsv"
      />
    </div>

    <CurveLegend :curves="curves" @remove="removeCurve" />

    <div class="chart-wrap">
      <div v-if="!curves.length" class="empty-hint">请先解析文件，选择遥测量后点击「增加曲线」，再查询</div>
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
import { getTelemetryFileCurve, startFileParsePoll } from '@/api/payload/telemetry'
import { CurveChartTools, CurveLegend, TimeSeriesChart } from '@/components/TimeSeriesChart'
import cache from '@/plugins/cache'
import { exportChartWindowCsv, MAX_CURVES, curveKey, normalizePoints, useCurveChartPage } from '@/utils/curvePage'

const PREFS_KEY = 'payload:fileCurve:prefs:v1'
const PARSE_TIMEOUT_MS = 60000

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
let parseJob = null
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
  tsChart.value?.render()
  tsChart.value?.scheduleResize()
  queryCurves()
}

function removeCurve(key) {
  curves.value = curves.value.filter(c => c.key !== key)
  releaseColor(key)
  tsChart.value?.render()
  tsChart.value?.scheduleResize()
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
    tsChart.value?.resetTimeWindow()
    tsChart.value?.render()
    ElMessage.success('已加载文件曲线')
  } catch (e) {
    ElMessage.error(e?.message || '查询失败')
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
