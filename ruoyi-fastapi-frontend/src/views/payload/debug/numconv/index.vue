<template>
  <div class="app-container numconv-page">
    <section class="conv-section">
      <h3 class="section-title">数字转 HEX</h3>
      <el-form :inline="true" class="conv-form" @submit.prevent>
        <el-form-item label="数字类型">
          <el-select v-model="numType" style="width: 120px" @change="persistPrefs">
            <el-option v-for="item in NUM_TYPES" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数字">
          <el-input
            v-model="numText"
            clearable
            placeholder="十进制，浮点可用科学计数法"
            style="width: 360px"
            @keyup.enter="onNumberCalc"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onNumberCalc">计算</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="numRows" border stripe class="result-table">
        <el-table-column prop="input" label="输入" min-width="160" show-overflow-tooltip />
        <el-table-column label="大端" min-width="200">
          <template #default="{ row }">
            <span class="mono" @dblclick="copyCell(row.be)">{{ row.be }}</span>
          </template>
        </el-table-column>
        <el-table-column label="小端" min-width="200">
          <template #default="{ row }">
            <span class="mono" @dblclick="copyCell(row.le)">{{ row.le }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-divider />

    <section class="conv-section">
      <h3 class="section-title">HEX 转数字</h3>
      <el-form class="conv-form" @submit.prevent>
        <el-form-item>
          <template #label>
            HEX
            <HexInputTip />
          </template>
          <div class="hex-line">
            <el-input
              :model-value="hexText"
              clearable
              placeholder="十六进制，空格可选"
              style="width: 360px"
              @update:model-value="onHexInput"
              @blur="onHexBlur"
              @keyup.enter="onHexCalc"
            />
            <el-checkbox v-model="padTail" @change="persistPrefs">后面补零</el-checkbox>
            <el-tooltip placement="top" :show-after="200">
              <template #content>
                字节数少于该类型时：勾选则在末尾补 00（如 01 → 01 00）；<br />
                取消则在开头补 00（如 01 → 00 01）。<br />
                字节数多于该类型时，只取前面相应的字节。输入最多 8 字节。
              </template>
              <el-icon class="tip-icon" @click.stop><QuestionFilled /></el-icon>
            </el-tooltip>
            <el-radio-group v-model="endian" class="endian-group">
              <el-radio value="be">大端</el-radio>
              <el-radio value="le">小端</el-radio>
            </el-radio-group>
            <el-button type="primary" class="hex-calc" @click="onHexCalc">计算</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-table :data="hexRows" border stripe empty-text="输入 HEX 后计算" class="result-table hex-table">
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column label="结果" min-width="180">
          <template #default="{ row }">
            <span class="mono" @dblclick="copyCell(row.result)">{{ row.result }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大端" min-width="200">
          <template #default="{ row }">
            <span class="mono" @dblclick="copyCell(row.be)">{{ row.be }}</span>
          </template>
        </el-table-column>
        <el-table-column label="小端" min-width="200">
          <template #default="{ row }">
            <span class="mono" @dblclick="copyCell(row.le)">{{ row.le }}</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-divider />

    <section class="conv-section">
      <h3 class="section-title">整数进制转换</h3>
      <div class="base-table">
        <div class="base-input-line">
          <span class="base-label">整数</span>
          <el-input
            v-model="baseInput"
            clearable
            placeholder="非负整数"
            class="base-value"
            @keyup.enter="onBaseCalc"
          />
          <div class="base-extra">
            <span class="extra-label">输入进制</span>
            <el-input-number
              v-model="inputBase"
              :min="2"
              :max="64"
              :step="1"
              :precision="0"
              controls-position="right"
              style="width: 120px"
            />
            <el-button type="primary" @click="onBaseCalc">计算</el-button>
          </div>
        </div>
        <p v-if="baseError" class="base-error">{{ baseError }}</p>
        <el-table :data="[{}]" border class="base-result-table">
          <el-table-column v-for="item in PRESET_BASES" :key="item.base" :label="item.label" min-width="140">
            <template #default>
              <div class="base-cell">
                <span class="mono">{{ displayBase(item) }}</span>
                <el-icon
                  class="copy-icon"
                  :class="{ 'is-disabled': !baseCell(item.label) }"
                  @click="copyCell(baseCell(item.label))"
                >
                </el-icon>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <div class="base-custom-line">
          <span class="extra-label">自定义进制</span>
          <el-input-number
            v-model="customBase"
            :min="2"
            :max="64"
            :step="1"
            :precision="0"
            controls-position="right"
            style="width: 120px"
            @change="refreshCustom"
          />
          <el-input :model-value="customValue" readonly class="base-value custom-value">
            <template #suffix>
              <el-icon class="copy-icon" :class="{ 'is-disabled': !customValue }" @click="copyCell(customValue)">
                <CopyDocument />
              </el-icon>
            </template>
          </el-input>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup name="Numconv">
/** 调试-数字转换：数字与 HEX 互转，以及 2–64 整数进制。 */
import { CopyDocument, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import HexInputTip from '@/components/Payload/HexInputTip.vue'
import cache from '@/plugins/cache'
import { HEX_INPUT_WARN, isHexText, normalizeHexDisplay } from '@/utils/payloadRawData'
import { NUM_TYPES, convertBase, getNumType, groupBinary, hexToNumberRows, numberToHex } from '@/utils/numconv'

const PREFS_KEY = 'payload:numconv:prefs:v1'
const PRESET_BASES = [
  { label: '二进制', base: 2 },
  { label: '八进制', base: 8 },
  { label: '十进制', base: 10 },
  { label: '十六进制', base: 16 },
  { label: 'Base64', base: 64 }
]

const saved = cache.local.getJSON(PREFS_KEY, {}) || {}

const numType = ref(getNumType(saved.numType) ? saved.numType : 'int16')
const numText = ref(saved.numText || '')
const numRows = ref([{ input: '', be: '', le: '' }])

const hexText = ref(saved.hexText || '')
const padTail = ref(saved.padTail !== false)
const endian = ref(saved.endian === 'le' ? 'le' : 'be')
const hexRows = ref([])

const baseInput = ref(saved.baseInput == null ? '42' : String(saved.baseInput))
const inputBase = ref(clampBase(saved.inputBase, 10))
const customBase = ref(clampBase(saved.customBase, 42))
const baseError = ref('')
const baseRows = ref(PRESET_BASES.map(item => ({ label: item.label, value: '' })))
const customValue = ref('')

function clampBase(value, fallback) {
  const n = Number(value)
  if (!Number.isInteger(n) || n < 2 || n > 64) return fallback
  return n
}

function persistPrefs() {
  cache.local.setJSON(PREFS_KEY, {
    numType: numType.value,
    numText: numText.value,
    hexText: hexText.value,
    padTail: !!padTail.value,
    endian: endian.value,
    baseInput: baseInput.value,
    inputBase: inputBase.value,
    customBase: customBase.value
  })
}

watch([numType, numText, hexText, padTail, endian, baseInput, inputBase, customBase], persistPrefs)

function baseCell(label) {
  return baseRows.value.find(row => row.label === label)?.value || ''
}

function displayBase(item) {
  const value = baseCell(item.label)
  return item.base === 2 ? groupBinary(value) : value
}

function refreshCustom(nextBase) {
  const base = nextBase == null ? customBase.value : nextBase
  try {
    customValue.value = convertBase(baseInput.value, Number(inputBase.value), Number(base))
  } catch {
    customValue.value = ''
  }
}

function copyCell(text) {
  const s = String(text ?? '')
  if (!s || s === '-') return
  navigator.clipboard.writeText(s).then(
    () => ElMessage.success('复制成功'),
    () => ElMessage.error('复制失败')
  )
}

function onNumberCalc() {
  const got = numberToHex(numText.value, numType.value)
  if (got.error) {
    ElMessage.warning(got.error)
    return
  }
  numRows.value = [got]
}

function onHexInput(next) {
  const raw = String(next ?? '')
  if (raw && !isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  hexText.value = raw
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

function onHexCalc() {
  const raw = String(hexText.value || '')
  if (!raw.trim()) {
    ElMessage.warning('请输入 HEX')
    return
  }
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  if (!norm) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  hexText.value = norm
  const got = hexToNumberRows(norm, { padTail: padTail.value, endian: endian.value })
  if (got.error) {
    ElMessage.warning(got.error)
    return
  }
  hexRows.value = got.rows
}

function onBaseCalc() {
  let rows
  try {
    rows = PRESET_BASES.map(item => ({
      label: item.label,
      value: convertBase(baseInput.value, Number(inputBase.value), item.base)
    }))
  } catch (err) {
    baseError.value = err.message || '无法转换'
    baseRows.value = PRESET_BASES.map(item => ({ label: item.label, value: '' }))
    customValue.value = ''
    return
  }
  let custom = ''
  try {
    custom = convertBase(baseInput.value, Number(inputBase.value), Number(customBase.value))
  } catch (err) {
    baseError.value = err.message || '无法转换'
    baseRows.value = rows
    customValue.value = ''
    return
  }
  baseError.value = ''
  baseRows.value = rows
  customValue.value = custom
}
</script>

<style scoped>
.section-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}
.conv-form :deep(.el-form-item) {
  margin-bottom: 12px;
}
.hex-line {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: nowrap;
}
.endian-group :deep(.el-radio) {
  margin-right: 8px;
}
.endian-group :deep(.el-radio:last-child) {
  margin-right: 0;
}
.hex-calc {
  margin-left: 16px;
}
.tip-icon {
  cursor: help;
  color: var(--el-text-color-secondary);
}
.result-table {
  width: 100%;
}
.mono {
  font-family: ui-monospace, Consolas, monospace;
  cursor: copy;
}
.base-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hex-table :deep(.el-table__empty-block) {
  min-height: 40px;
}
.hex-table :deep(.el-table__empty-text) {
  line-height: 23px;
}
.result-table :deep(.cell) {
  min-height: 23px;
  white-space: nowrap;
}
.base-input-line,
.base-extra,
.base-custom-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.base-input-line {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  column-gap: 8px;
  align-items: center;
}
.base-label,
.extra-label {
  color: var(--el-text-color-regular);
}
.base-label {
  text-align: right;
}
.base-error {
  margin: 0;
  color: var(--el-color-danger);
}
.base-result-table {
  width: 100%;
}
.base-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 24px;
}
.custom-value {
  width: 280px;
}
.base-value :deep(.el-input__inner) {
  font-family: ui-monospace, Consolas, monospace;
}
.copy-icon {
  cursor: pointer;
  color: var(--el-text-color-secondary);
}
.copy-icon:hover {
  color: var(--el-color-primary);
}
.copy-icon.is-disabled {
  cursor: not-allowed;
  opacity: 0.35;
}
</style>
