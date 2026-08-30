<template>
  <div class="app-container tm-calc-page">
    <el-form :inline="true" label-width="70px" class="calc-form">
      <el-form-item label="遥测表">
        <TelemetryPageSelect v-model="tmType" :pages="tmPages" style="width: 280px" @change="onTypeChange" />
      </el-form-item>
      <el-form-item label="遥测量">
        <el-select v-model="fieldId" filterable style="width: 220px" @change="persistFormCache">
          <el-option
            v-for="f in fields"
            :key="f.id"
            :label="`${f.id} ${f.name}`"
            :value="f.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <template #label>
          Hex
          <HexInputTip />
        </template>
        <el-input
          :model-value="hexText"
          clearable
          placeholder="字段 Hex（空格可选）"
          style="width: 200px"
          @update:model-value="onHexInput"
          @blur="onHexBlur"
          @keyup.enter="onCalc"
        />
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="padTail">后面补零</el-checkbox>
        <el-tooltip placement="top" :show-after="200">
          <template #content>
            按字段位数补齐字节：勾选则末尾补 00（如 33 01 02 → 33 01 02 00）；<br />
            取消则开头补 00（如 33 01 02 → 00 33 01 02）。
          </template>
          <el-icon class="pad-tip" @click.stop><QuestionFilled /></el-icon>
        </el-tooltip>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="calculating"
          :disabled="!canCalc"
          v-hasPermi="['payload:tmcalc:view']"
          @click="onCalc"
        >
          计算
        </el-button>
        <el-button :disabled="!rows.length" @click="onClearHistory">清空历史</el-button>
      </el-form-item>
    </el-form>

    <div class="tm-table-wrap">
      <el-table
        :data="rows"
        v-loading="loadingHistory"
        border
        stripe
        height="100%"
        empty-text="暂无计算记录"
        :row-class-name="rowClassName"
      >
        <el-table-column label="编号" width="100">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.cfg"
              placement="right"
              :show-after="200"
              effect="light"
              popper-class="tm-cfg-tooltip"
            >
              <template #content>
                <pre class="tm-cfg-json">{{ cfgJson(row.cfg) }}</pre>
              </template>
              <span class="id-cell">{{ row.id }}</span>
            </el-tooltip>
            <span v-else>{{ row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="参数名称" width="280" show-overflow-tooltip />
        <el-table-column label="当前值" width="180">
          <template #default="{ row }">
            <span :class="{ 'cell-err': row.err }">{{ row.show ?? row.value }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column prop="hex" label="HEX" min-width="140" show-overflow-tooltip />
        <el-table-column prop="ts" label="时间" width="200" />
      </el-table>
    </div>
  </div>
</template>

<script setup name="PayloadTmCalc">
import { QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getTelemetryDef } from '@/api/payload/config'
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'
import {
  calcTelemetryField,
  clearTelemetryCalcHistory,
  getTelemetryCalcHistory
} from '@/api/payload/tmCalc'
import { HEX_INPUT_WARN, isHexText, normalizeHexDisplay } from '@/utils/payloadRawData'
import HexInputTip from '@/components/Payload/HexInputTip.vue'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

const CACHE_KEY = 'payload:tmcalc:form'

const tmPages = ref([])
const tmType = ref('')
const fields = ref([])
const fieldId = ref('')
const hexText = ref('')
/** 字节不足时：勾选后面补 00，取消则前面补 00（由后端按字段 bits 补齐） */
const padTail = ref(true)
const rows = ref([])
const calculating = ref(false)
const loadingHistory = ref(false)
/** 恢复缓存时避免 onTypeChange 清掉已缓存的遥测量 */
let restoring = false

const canCalc = computed(
  () => !!(tmType.value && fieldId.value && String(hexText.value || '').trim())
)

function cfgJson(cfg) {
  try {
    return JSON.stringify(cfg, null, 2)
  } catch {
    return String(cfg || '')
  }
}

function loadFormCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return {}
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

function persistFormCache() {
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        tmType: tmType.value || '',
        fieldId: fieldId.value || '',
        hex: String(hexText.value || ''),
        padTail: !!padTail.value
      })
    )
  } catch {
    /* ignore */
  }
}

function formatHexBeforeSend() {
  const raw = String(hexText.value || '')
  if (!raw.trim()) {
    ElMessage.warning('请输入 Hex 文本')
    return null
  }
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return null
  }
  const norm = normalizeHexDisplay(raw)
  if (!norm) {
    ElMessage.warning(HEX_INPUT_WARN)
    return null
  }
  hexText.value = norm
  persistFormCache()
  return norm
}

function onHexBlur() {
  const raw = String(hexText.value || '')
  if (!raw.trim()) return
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  if (norm) hexText.value = norm
}

function onHexInput(next) {
  const raw = String(next ?? '')
  if (raw && !isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  hexText.value = raw
}

watch([tmType, fieldId, hexText, padTail], () => {
  if (!restoring) persistFormCache()
})

function rowClassName({ row }) {
  return row?.err ? 'tm-calc-row-err' : ''
}

async function loadPages() {
  const cached = loadFormCache()
  tmPages.value = await loadTelemetryPagesCached()
  const keys = new Set(tmPages.value.map((p) => p.key))
  if (cached.tmType && keys.has(cached.tmType)) {
    tmType.value = cached.tmType
  } else if (!tmType.value && tmPages.value.length) {
    tmType.value = tmPages.value[0].key
  }
  if (tmType.value) await loadFields(cached.fieldId)
}

async function loadFields(preferFieldId) {
  if (!tmType.value) {
    fields.value = []
    fieldId.value = ''
    return
  }
  const res = await getTelemetryDef(tmType.value)
  const list = res.data?.row || []
  fields.value = list
    .filter((r) => r?.id)
    .map((r) => ({ id: r.id, name: r.name || '', unit: r.unit || '' }))
  const ids = new Set(fields.value.map((f) => f.id))
  const prefer = preferFieldId || fieldId.value
  if (prefer && ids.has(prefer)) {
    fieldId.value = prefer
  } else {
    fieldId.value = fields.value[0]?.id || ''
  }
}

async function onTypeChange() {
  if (restoring) return
  fieldId.value = ''
  await loadFields()
}

async function loadHistory() {
  loadingHistory.value = true
  try {
    const res = await getTelemetryCalcHistory()
    rows.value = res.data || []
  } finally {
    loadingHistory.value = false
  }
}

async function onCalc() {
  if (!tmType.value || !fieldId.value) return
  const hex = formatHexBeforeSend()
  if (!hex) return
  calculating.value = true
  try {
    const res = await calcTelemetryField({
      type: tmType.value,
      field: fieldId.value,
      hex,
      padTail: !!padTail.value
    })
    const data = res.data || {}
    rows.value = data.history || []
    if (data.err) {
      ElMessage.warning(data.warnMsg || res.msg || '解析失败: 字段解析返回错误')
    } else {
      ElMessage.success(res.msg || '计算成功')
    }
  } catch {
    /* request 已提示（字段不存在等硬错误） */
  } finally {
    calculating.value = false
  }
}

async function onClearHistory() {
  try {
    await ElMessageBox.confirm('确认清空全部计算历史？', '提示', { type: 'warning' })
  } catch {
    return
  }
  await clearTelemetryCalcHistory()
  rows.value = []
  ElMessage.success('已清空')
}

onMounted(async () => {
  restoring = true
  const cached = loadFormCache()
  if (cached.hex) hexText.value = cached.hex
  if (typeof cached.padTail === 'boolean') padTail.value = cached.padTail
  try {
    await Promise.all([loadPages(), loadHistory()])
  } finally {
    restoring = false
    persistFormCache()
  }
})
</script>

<style scoped>
.tm-calc-page {
  padding: 12px 16px !important;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.calc-form {
  flex-shrink: 0;
  margin-bottom: 8px;
}
.calc-form :deep(.el-form-item) {
  margin-bottom: 8px;
  margin-right: 16px;
}
.pad-tip {
  margin-left: 2px;
  vertical-align: middle;
  color: var(--el-text-color-secondary);
  cursor: help;
}
.tm-table-wrap {
  flex: 1;
  min-height: 0;
}
.id-cell {
  cursor: help;
}
.tm-cfg-json {
  margin: 0;
  max-width: 420px;
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-all;
}
.cell-err {
  color: var(--el-color-danger);
}
</style>

<style>
.tm-cfg-tooltip {
  max-width: 460px;
}
.tm-calc-row-err > td {
  --el-table-tr-bg-color: var(--el-color-danger-light-9);
}
</style>
