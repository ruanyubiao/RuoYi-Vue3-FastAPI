<template>
  <div class="app-container timeconv-page">
    <el-alert
      class="timezone-tip"
      type="info"
      :closable="false"
      show-icon
      title="Unix 时间戳本身不带时区，只有在格式化为日期字符串时才体现时区差异。"
    />

    <section class="conv-section">
      <h3 class="section-title">协议时间换算</h3>
      <el-form class="epoch-form" @submit.prevent>
        <div class="form-line">
          <el-form-item label="协议时间纪元">
            <el-select
              v-model="selectedEpoch"
              :loading="epochLoading"
              placeholder="请选择协议纪元"
              class="epoch-select"
            >
              <el-option
                v-for="item in epochOptions"
                :key="item.id"
                :label="item.label"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="输入格式">
            <el-radio-group :model-value="inputFormat" @change="onFormatChange">
              <el-radio v-for="item in PROTOCOL_FORMATS" :key="item.id" :value="item.id">
                {{ item.label }}
              </el-radio>
            </el-radio-group>
          </el-form-item>
        </div>

        <div class="form-line fields-line">
          <template v-if="inputFormat === 'dec'">
            <el-form-item
              v-for="name in PROTOCOL_FIELD_NAMES"
              :key="`dec-${name}`"
              :label="PROTOCOL_FIELD_LIMITS[name].label"
              :error="fieldErrors[name]"
            >
              <el-input
                :model-value="decTexts[name]"
                clearable
                placeholder="非负整数"
                class="field-input"
                :maxlength="decMaxLen(name)"
                @update:model-value="onDecInput(name, $event)"
                @blur="normalizeDec(name)"
                @keyup.enter="onCalc"
              />
            </el-form-item>
          </template>
          <template v-else>
            <el-form-item
              v-for="name in PROTOCOL_FIELD_NAMES"
              :key="`hex-${name}`"
              :label="PROTOCOL_FIELD_LIMITS[name].label"
              :error="fieldErrors[name]"
            >
              <el-input
                :model-value="hexTexts[name]"
                clearable
                :placeholder="`${PROTOCOL_FIELD_LIMITS[name].hexChars} 位 HEX`"
                class="field-input"
                :maxlength="PROTOCOL_FIELD_LIMITS[name].hexChars"
                @update:model-value="onHexInput(name, $event)"
                @blur="normalizeHex(name)"
                @keyup.enter="onCalc"
              />
            </el-form-item>
          </template>
          <el-form-item>
            <el-button type="primary" @click="onCalc">计算</el-button>
          </el-form-item>
          <span class="field-hint">
            周、周内秒、毫秒是一组协议时间，计算后写入下方日期转换输入框。
          </span>
        </div>
      </el-form>
    </section>

    <el-divider />

    <section class="conv-section">
      <div class="date-line">
        <span class="date-label">
          日期时间
          <el-tooltip placement="top" :show-after="200">
            <template #content>
              Unix 时间戳本身不带时区，只有在格式化为日期字符串时才体现时区差异。<br />
              支持常见日期字符串，以及秒/毫秒时间戳；留空时按当前时刻刷新下方表格。
            </template>
            <el-icon class="tip-icon" @click.stop><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <el-input
          :model-value="dateInput"
          clearable
          class="date-input"
          placeholder="输入日期字符串或时间戳；留空显示当前时间"
          @update:model-value="onDateInput"
          @clear="onDateInput('')"
        />
        <el-tooltip
          :content="dateLive ? '暂停自动刷新' : '运行自动刷新'"
          placement="top"
          :show-after="200"
        >
          <el-button
            link
            class="live-btn"
            :disabled="!dateEmpty"
            :aria-label="dateLive ? '暂停自动刷新' : '运行自动刷新'"
            @click="dateLive = !dateLive"
          >
            <el-icon :size="22">
              <VideoPause v-if="dateLive" />
              <VideoPlay v-else />
            </el-icon>
          </el-button>
        </el-tooltip>
      </div>
      <p v-if="dateResult.error" class="date-error">{{ dateResult.error }}</p>
      <el-table
        :data="dateRows"
        border
        stripe
        class="result-table"
        empty-text="输入日期字符串后显示各格式"
      >
        <el-table-column prop="label" label="时间格式" width="180" />
        <el-table-column label="时间格式化显示" min-width="280">
          <template #default="{ row }">
            <div class="value-cell">
              <span class="mono">{{ row.value }}</span>
              <el-icon class="copy-icon" @click="copyCell(row.value)">
                <CopyDocument />
              </el-icon>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="260" show-overflow-tooltip />
      </el-table>
    </section>
  </div>
</template>

<script setup name="Timeconv">
/** 调试-时间转换：协议纪元 + 周/周内秒/毫秒换算，以及日期格式表。 */
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { CopyDocument, QuestionFilled, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listTimeconvEpochs } from '@/api/payload/timeconv'
import cache from '@/plugins/cache'
import {
  PROTOCOL_FIELD_LIMITS,
  PROTOCOL_FIELD_NAMES,
  PROTOCOL_FORMATS,
  U32_MAX,
  dateFormatRows,
  formatProtocolValue,
  parseDateInput,
  parseProtocolValue,
  protocolToUnixMs
} from '@/utils/timeconv'

const NONE_EPOCH = { id: 'none', label: 'NONE: 1970-01-01', epochUtcSec: 0, dateUtc: '1970-01-01' }
const PREFS_KEY = 'payload:timeconv:prefs:v1'
const DATE_LIVE_MS = 50

const saved = cache.local.getJSON(PREFS_KEY, {}) || {}

const epochOptions = ref([NONE_EPOCH])
const selectedEpoch = ref(typeof saved.selectedEpoch === 'string' ? saved.selectedEpoch : NONE_EPOCH.id)
const epochLoading = ref(false)
const inputFormat = ref(normalizeSavedFormat(saved.inputFormat))
const decTexts = reactive(loadFieldTexts(saved.decTexts, { week: '0', sow: '0', ms: '0' }))
const hexTexts = reactive(loadFieldTexts(saved.hexTexts, { week: '00', sow: '00', ms: '00' }))
const fieldValues = reactive({ week: 0, sow: 0, ms: 0 })
const fieldErrors = reactive({ week: '', sow: '', ms: '' })
const dateInput = ref('')
const dateInputUnit = ref('')
const dateLive = ref(true)
const nowTick = ref(0)

let liveTimer = null

const selectedEpochOption = computed(
  () => epochOptions.value.find(item => item.id === selectedEpoch.value) || NONE_EPOCH
)
const dateEmpty = computed(() => !String(dateInput.value ?? '').trim())
const dateResult = computed(() =>
  parseDateInput(dateInput.value, dateInputUnit.value === 'ms' ? { unit: 'ms' } : undefined)
)
const dateRows = computed(() => {
  void nowTick.value
  if (dateResult.value.error) return []
  if (dateEmpty.value) return dateFormatRows(new Date())
  return dateResult.value.date ? dateFormatRows(dateResult.value.date) : []
})

function normalizeSavedFormat(format) {
  return PROTOCOL_FORMATS.some(item => item.id === format) ? format : 'dec'
}

function loadFieldTexts(raw, fallback) {
  const out = { ...fallback }
  if (!raw || typeof raw !== 'object') return out
  for (const name of PROTOCOL_FIELD_NAMES) {
    if (raw[name] != null) out[name] = String(raw[name])
  }
  return out
}

function hexWidth(name) {
  return PROTOCOL_FIELD_LIMITS[name].hexChars
}

function formatHex(name, value, endian) {
  return formatProtocolValue(value, endian, hexWidth(name))
}

function decMaxLen(name) {
  return String(PROTOCOL_FIELD_LIMITS[name].max).length
}

function activeTexts() {
  return inputFormat.value === 'dec' ? decTexts : hexTexts
}

function parseActiveField(name) {
  const limit = PROTOCOL_FIELD_LIMITS[name]
  return parseProtocolValue(activeTexts()[name], inputFormat.value, limit.max, limit.label)
}

function setFieldOk(name, value) {
  fieldValues[name] = value
  fieldErrors[name] = ''
}

function setFieldError(name, message) {
  fieldErrors[name] = message
}

function persistPrefs() {
  cache.local.setJSON(PREFS_KEY, {
    selectedEpoch: selectedEpoch.value,
    inputFormat: inputFormat.value,
    decTexts: { ...decTexts },
    hexTexts: { ...hexTexts }
  })
}

function syncLiveTimer() {
  if (liveTimer) {
    clearInterval(liveTimer)
    liveTimer = null
  }
  if (dateEmpty.value && dateLive.value) {
    liveTimer = setInterval(() => {
      nowTick.value += 1
    }, DATE_LIVE_MS)
  }
}

async function loadEpochs() {
  epochLoading.value = true
  try {
    const res = await listTimeconvEpochs()
    const items = Array.isArray(res.data) ? res.data : res.data?.items
    if (Array.isArray(items) && items.length) {
      epochOptions.value = items
      if (!items.some(item => item.id === selectedEpoch.value)) {
        selectedEpoch.value = items.find(item => item.id === 'none')?.id || items[0].id
      }
    }
  } catch {
    // 请求层已提示错误；保留 NONE 选项，日期转换仍可使用
  } finally {
    epochLoading.value = false
  }
}

function onDecInput(name, value) {
  const max = PROTOCOL_FIELD_LIMITS[name].max
  const maxLen = String(max).length
  let next = String(value ?? '').replace(/\D/g, '').slice(0, maxLen)
  if (next) {
    try {
      const big = BigInt(next)
      if (big > BigInt(max)) {
        while (next && BigInt(next) > BigInt(max)) next = next.slice(0, -1)
      }
    } catch {
      next = ''
    }
  }
  decTexts[name] = next
  try {
    setFieldOk(name, parseProtocolValue(next, 'dec', max, PROTOCOL_FIELD_LIMITS[name].label))
  } catch (err) {
    setFieldError(name, err.message)
  }
}

function onHexInput(name, value) {
  const next = String(value ?? '')
    .replace(/[^0-9a-fA-F]/g, '')
    .slice(0, hexWidth(name))
    .toUpperCase()
  hexTexts[name] = next
  try {
    setFieldOk(
      name,
      parseProtocolValue(next, inputFormat.value, PROTOCOL_FIELD_LIMITS[name].max, PROTOCOL_FIELD_LIMITS[name].label)
    )
  } catch (err) {
    setFieldError(name, err.message)
  }
}

function normalizeDec(name) {
  try {
    const value = parseActiveField(name)
    setFieldOk(name, value)
    decTexts[name] = formatProtocolValue(value, 'dec')
  } catch (err) {
    setFieldError(name, err.message)
  }
}

function normalizeHex(name) {
  try {
    const value = parseActiveField(name)
    setFieldOk(name, value)
    hexTexts[name] = formatHex(name, value, inputFormat.value)
  } catch (err) {
    setFieldError(name, err.message)
  }
}

/**
 * 从当前格式读字段值；HEX 可能超过字段上限（周内秒 6 位 / 毫秒 4 位），超限钳到 max。
 * 非法输入按 0。
 */
function readClampedField(name, format) {
  const limit = PROTOCOL_FIELD_LIMITS[name]
  const texts = format === 'dec' ? decTexts : hexTexts
  try {
    const raw = parseProtocolValue(texts[name], format, U32_MAX, limit.label)
    return Math.min(raw, limit.max)
  } catch {
    return 0
  }
}

/** 切换格式时互转：整数 ↔ HEX / 大端 ↔ 小端；超限钳到字段最大值并同步两组显示。 */
function onFormatChange(nextFormat) {
  if (nextFormat === inputFormat.value) return
  const prevFormat = inputFormat.value
  for (const name of PROTOCOL_FIELD_NAMES) {
    const value = readClampedField(name, prevFormat)
    setFieldOk(name, value)
    decTexts[name] = formatProtocolValue(value, 'dec')
    const hexEndian = nextFormat === 'dec' ? (prevFormat === 'dec' ? 'be' : prevFormat) : nextFormat
    hexTexts[name] = formatHex(name, value, hexEndian)
  }
  inputFormat.value = nextFormat
}

function onDateInput(value) {
  dateInput.value = value
  dateInputUnit.value = ''
}

function onCalc() {
  for (const name of PROTOCOL_FIELD_NAMES) {
    try {
      setFieldOk(name, parseActiveField(name))
      if (inputFormat.value === 'dec') {
        decTexts[name] = formatProtocolValue(fieldValues[name], 'dec')
      } else {
        hexTexts[name] = formatHex(name, fieldValues[name], inputFormat.value)
      }
    } catch (err) {
      setFieldError(name, err.message)
      ElMessage.warning(err.message)
      return
    }
  }
  try {
    const unixMs = protocolToUnixMs({
      epochUtcSec: selectedEpochOption.value.epochUtcSec,
      ...fieldValues
    })
    dateInput.value = String(unixMs)
    dateInputUnit.value = 'ms'
  } catch (err) {
    ElMessage.warning(err.message)
  }
}

function copyCell(text) {
  const value = String(text ?? '')
  if (!value) return
  navigator.clipboard.writeText(value).then(
    () => ElMessage.success('复制成功'),
    () => ElMessage.error('复制失败')
  )
}

watch([selectedEpoch, inputFormat, decTexts, hexTexts], persistPrefs, { deep: true })
watch([dateEmpty, dateLive], syncLiveTimer, { immediate: true })

onMounted(loadEpochs)
onUnmounted(() => {
  if (liveTimer) {
    clearInterval(liveTimer)
    liveTimer = null
  }
})
</script>

<style scoped>
.timezone-tip {
  margin-bottom: 16px;
}
.section-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}
.form-line {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0 16px;
}
.fields-line {
  align-items: center;
}
.epoch-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.epoch-select {
  width: 240px;
}
.field-input {
  width: 114px;
}
.field-input :deep(.el-input__inner) {
  font-family: ui-monospace, Consolas, monospace;
}
.field-hint {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
  flex: 1 1 220px;
  align-self: center;
}
.date-line {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 12px;
  width: 100%;
}
.date-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  color: var(--el-text-color-regular);
  font-size: 14px;
  line-height: 32px;
}
.tip-icon {
  color: var(--el-text-color-secondary);
  cursor: help;
  font-size: 14px;
}
.tip-icon:hover {
  color: var(--el-color-primary);
}
.date-input {
  flex: 1 1 auto;
  min-width: 200px;
  max-width: 760px;
}
.date-input :deep(.el-input__inner) {
  font-family: ui-monospace, Consolas, monospace;
}
.live-btn {
  flex: none;
  margin-left: auto;
  padding: 4px;
  height: auto;
  color: var(--el-text-color-regular);
}
.live-btn:hover,
.live-btn:focus {
  color: var(--el-color-primary);
}
.live-btn.is-disabled {
  color: var(--el-text-color-disabled);
}
.date-error {
  margin: 0 0 12px;
  color: var(--el-color-danger);
}
.result-table {
  width: 100%;
}
.value-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mono {
  font-family: ui-monospace, Consolas, monospace;
  word-break: break-all;
}
.copy-icon {
  flex: none;
  cursor: pointer;
  color: var(--el-text-color-secondary);
}
.copy-icon:hover {
  color: var(--el-color-primary);
}
.result-table :deep(.cell) {
  white-space: normal;
}
@media (max-width: 640px) {
  .epoch-select,
  .field-input {
    width: 100%;
  }
}
</style>
