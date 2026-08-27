<template>
  <el-dialog
    :model-value="modelValue"
    width="520px"
    destroy-on-close
    class="can-connect-dialog"
    @update:model-value="onVisibleChange"
    @opened="onOpened"
  >
    <template #header>
      <span class="dlg-title">{{ title }}</span>
    </template>
    <el-form label-width="100px" class="conn-form">
      <el-form-item label="厂商">
        <div class="port-row">
          <el-select
            :key="vendorSelectKey"
            v-model="form.vendor"
            :disabled="opening"
            placeholder="请选择厂商"
            class="conn-ctrl"
          >
            <el-option
              v-for="v in vendorOptions"
              :key="`${v.value}-${v.name}`"
              :label="v.label"
              :value="v.value"
            />
          </el-select>
          <el-button
            type="primary"
            plain
            icon="Refresh"
            :loading="refreshing"
            :disabled="opening"
            @click="refreshVendors"
          >
            刷新
          </el-button>
        </div>
      </el-form-item>
      <el-form-item label="设备索引号">
        <el-select
          v-model="form.devIndex"
          :disabled="opening || devIndexOptions.length <= 1"
          class="conn-ctrl"
        >
          <el-option
            v-for="d in devIndexOptions"
            :key="d.value"
            :label="d.label"
            :value="d.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="通道号">
        <el-select v-model="form.canIndex" :disabled="opening" class="conn-ctrl">
          <el-option
            v-for="ch in canIndexOptions"
            :key="ch.value"
            :label="ch.label"
            :value="ch.value"
            :disabled="ch.disabled"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="波特率">
        <el-select v-model="form.baudRate" :disabled="opening || lockBaud" class="conn-ctrl">
          <el-option v-for="b in displayedBaudOptions" :key="b.value" :label="b.label" :value="b.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <template #label>
          组装器
          <el-tooltip :content="ASSEMBLER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select
          v-model="form.assemblerId"
          placeholder="请选择组装器"
          class="conn-ctrl"
          :disabled="opening || assemblerLocked"
          @change="onAssemblerChange"
        >
          <el-option v-for="a in assemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">CAN-BIU / CAN-XL 走协议组帧；透传对应协议 NONE（裸测）</div>
      </el-form-item>
      <el-form-item>
        <template #label>
          解释器
          <el-tooltip :content="PARSER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select
          v-model="form.parserId"
          :clearable="!parserLocked"
          placeholder="请选择解释器"
          class="conn-ctrl"
          :disabled="opening || parserLocked"
        >
          <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">不绑定则不解析数据</div>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="opening"
          :disabled="form.vendor == null || selectedChannelDisabled"
          @click="submit"
        >{{ confirmLabel }}</el-button>
        <el-button @click="onVisibleChange(false)">取消</el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listCanVendors, listCanChannels, listParsers, listAssemblers, openCanChannel } from '@/api/payload/device'
import { setActiveDevice } from '@/utils/deviceSnapshotCache'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'
import { isConnectCfgFieldLocked } from '@/utils/deviceConnectDefaults'
import {
  ASSEMBLER_CAN_BIU,
  ASSEMBLER_PASSTHROUGH,
  PARSER_TM_CAN_BIU,
  CAN_ASSEMBLER_TO_PARSER,
  FALLBACK_ASSEMBLERS_CAN,
  FALLBACK_PARSERS_CAN
} from '@/utils/pipelineIds'

const baudOptions = [
  { value: 1000, label: '1000kbps' },
  { value: 800, label: '800kbps' },
  { value: 500, label: '500kbps' },
  { value: 250, label: '250kbps' },
  { value: 125, label: '125kbps' },
  { value: 100, label: '100kbps' },
  { value: 50, label: '50kbps' },
  { value: 20, label: '20kbps' },
  { value: 10, label: '10kbps' },
  { value: 5, label: '5kbps' }
]

const LOCKED_BAUD = 500

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '新建 CAN 连接' },
  source: { type: String, default: 'home' },
  prefsKey: { type: String, default: 'payload:control:canPrefs' },
  showBindingTips: { type: Boolean, default: true },
  /**
   * 线缆：null=不传（首页）；0=A / 1=B（遥控 CAN-A/B）
   */
  cableFlag: { type: Number, default: null },
  /**
   * 兼容旧调用；组装器/解释器是否锁定改由 preset.lockAssembler / lockParser
   *（cfg 字段非空才锁）。空字段可改。
   */
  lockPipeline: { type: Boolean, default: false },
  /** 遥控页锁定波特率（取自 preset.baudChoices / baudRate，默认 500） */
  lockBaud: { type: Boolean, default: false },
  /** 预设：baudRate/baudChoices/nodeAddrTo/assemblerId/parserId（可选 canIndex/devIndex） */
  preset: { type: Object, default: null },
  /** false=禁止复用已开通道（首页新建）；已开项禁用且确认键保持「打开」 */
  allowReuse: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'success'])

/** cfg 字段非空才锁；首页无 preset 不锁。lockPipeline 不再单独锁空字段。 */
const assemblerLocked = computed(() => {
  const p = props.preset
  if (!p || typeof p !== 'object') return false
  if (typeof p.lockAssembler === 'boolean') return p.lockAssembler
  return isConnectCfgFieldLocked(p.assemblerId)
})
const parserLocked = computed(() => {
  const p = props.preset
  if (!p || typeof p !== 'object') return false
  if (typeof p.lockParser === 'boolean') return p.lockParser
  return isConnectCfgFieldLocked(p.parserId)
})

const form = reactive({
  vendor: null,
  devIndex: 0,
  canIndex: 0,
  baudRate: 500,
  nodeAddrTo: 0x0d,
  assemblerId: ASSEMBLER_CAN_BIU,
  parserId: PARSER_TM_CAN_BIU
})

const ASSEMBLER_PARSER_DEFAULTS = CAN_ASSEMBLER_TO_PARSER
const opening = ref(false)
const refreshing = ref(false)
const vendorSelectKey = ref(0)
const vendors = ref([])
/** @type {import('vue').Ref<Array<{vendor:number,devIndex:number,canIndex:number,baudRate?:number|null,deviceId?:string}>>} */
const openedChannels = ref([])
const parserOptions = ref([])
const assemblerOptions = ref([])

function lockedBaudValue() {
  const choices = props.preset?.baudChoices
  if (Array.isArray(choices) && choices.length) {
    const n = Number(choices[0])
    if (Number.isFinite(n)) return n
  }
  if (props.preset?.baudRate != null) {
    const n = Number(props.preset.baudRate)
    if (Number.isFinite(n)) return n
  }
  return LOCKED_BAUD
}

const displayedBaudOptions = computed(() => {
  if (props.lockBaud) {
    const choices =
      Array.isArray(props.preset?.baudChoices) && props.preset.baudChoices.length
        ? props.preset.baudChoices
        : [lockedBaudValue()]
    return choices.map(v => {
      const n = Number(v)
      return { value: n, label: `${n}kbps` }
    })
  }
  return baudOptions
})

const requiredBaud = computed(() => (props.lockBaud ? lockedBaudValue() : Number(form.baudRate)))

/** 当前厂商 SDK 声明的通道数；下拉为 0..N-1 */
const channelCount = computed(() => {
  const hit = vendors.value.find(v => v.value === form.vendor)
  const n = Number(hit?.channelCount)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 2
})

function getOpenedChannel(vendor, devIndex, canIndex) {
  return openedChannels.value.find(
    c =>
      Number(c.vendor) === Number(vendor) &&
      Number(c.devIndex) === Number(devIndex) &&
      Number(c.canIndex) === Number(canIndex)
  )
}

function isChannelOpened(vendor, devIndex, canIndex) {
  return !!getOpenedChannel(vendor, devIndex, canIndex)
}

function isChannelBaudMatch(opened) {
  if (!opened) return true
  if (!props.lockBaud) return true
  const baud = Number(opened.baudRate)
  // 未知波特率时允许复用（兼容旧进程）；已知且不等于要求值则禁止
  if (!Number.isFinite(baud)) return true
  return baud === Number(requiredBaud.value)
}

function isVendorOpened(vendor) {
  return openedChannels.value.some(c => Number(c.vendor) === Number(vendor))
}

function isDevIndexOpened(vendor, devIndex) {
  return openedChannels.value.some(
    c => Number(c.vendor) === Number(vendor) && Number(c.devIndex) === Number(devIndex)
  )
}

const vendorOptions = computed(() =>
  (vendors.value || []).map(v => {
    const n = Number(v.channelCount)
    const ch = Number.isFinite(n) && n > 0 ? ` · ${n}通道` : ''
    const base = `${v.value} - ${v.name || ''}${ch}`
    return {
      ...v,
      label: isVendorOpened(v.value) ? `${base} - 已连接` : base
    }
  })
)

/** 设备索引：至少 0；并合入该厂商已打开卡号，便于多卡提示 */
const devIndexOptions = computed(() => {
  const set = new Set([0, Number(form.devIndex) || 0])
  for (const c of openedChannels.value) {
    if (Number(c.vendor) === Number(form.vendor)) {
      set.add(Number(c.devIndex) || 0)
    }
  }
  return [...set]
    .filter(n => Number.isFinite(n) && n >= 0)
    .sort((a, b) => a - b)
    .map(value => ({
      value,
      label: isDevIndexOpened(form.vendor, value) ? `${value} - 已连接` : String(value)
    }))
})

const canIndexOptions = computed(() =>
  Array.from({ length: channelCount.value }, (_, i) => {
    const base = `${i}:CAN${i}`
    const opened = getOpenedChannel(form.vendor, form.devIndex, i)
    if (!opened) {
      return { value: i, label: base, disabled: false }
    }
    const match = isChannelBaudMatch(opened)
    return {
      value: i,
      label: match ? `${base} - 已连接` : `${base} - 已连接 - 波特率不符`,
      // 禁止复用时已开通道一律不可选；锁定波特率时不符也不可选
      disabled: !props.allowReuse || (props.lockBaud && !match)
    }
  })
)

const selectedChannelDisabled = computed(() => {
  const hit = canIndexOptions.value.find(o => o.value === form.canIndex)
  return !!hit?.disabled
})

/** 通道已打开且波特率可复用 → 「使用」；否则新建 「打开」 */
const canReuseExisting = computed(() => {
  if (!props.allowReuse) return false
  const opened = getOpenedChannel(form.vendor, form.devIndex, form.canIndex)
  return !!opened && isChannelBaudMatch(opened)
})
const confirmLabel = computed(() => (canReuseExisting.value ? '使用' : '打开'))

function clampCanIndex() {
  const max = Math.max(0, channelCount.value - 1)
  if (form.canIndex > max) form.canIndex = max
  if (form.canIndex < 0) form.canIndex = 0
  // 锁定波特率或禁止复用时：当前选中不可用则改选可用通道
  if (props.lockBaud || !props.allowReuse) {
    const cur = canIndexOptions.value.find(o => o.value === form.canIndex)
    if (cur?.disabled) {
      const free = canIndexOptions.value.find(o => !o.disabled)
      if (free) form.canIndex = free.value
    }
  }
}

function clampDevIndex() {
  const opts = devIndexOptions.value
  if (!opts.length) {
    form.devIndex = 0
    return
  }
  if (!opts.some(o => o.value === form.devIndex)) {
    form.devIndex = opts[0].value
  }
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

function readPrefs() {
  try {
    const raw = localStorage.getItem(props.prefsKey)
    if (!raw) return null
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : null
  } catch {
    return null
  }
}

function writePrefs(data) {
  try {
    localStorage.setItem(props.prefsKey, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

function pickOption(saved, options, getValue, fallback) {
  const list = options || []
  if (saved == null || saved === '') return fallback
  return list.some(o => getValue(o) === saved) ? saved : fallback
}

function isPcieVendor(v) {
  return `${v.key || ''} ${v.name || ''}`.toUpperCase().includes('PCIE')
}

function pickDefaultVendor(list) {
  if (!list.length) return null
  return (list.find(isPcieVendor) || list[0]).value
}

function mapVendors(raw) {
  return (raw || []).map(v => ({
    value: v.value,
    key: v.key,
    name: v.name,
    channelCount: Number(v.channelCount) > 0 ? Number(v.channelCount) : 2
  }))
}

function applyPreset(p) {
  if (!p || typeof p !== 'object') return
  if (p.devIndex != null) form.devIndex = Number(p.devIndex)
  if (p.canIndex != null) form.canIndex = Number(p.canIndex)
  if (p.baudRate != null) form.baudRate = Number(p.baudRate)
  if (p.nodeAddrTo != null) form.nodeAddrTo = Number(p.nodeAddrTo)
  if (p.assemblerId) form.assemblerId = p.assemblerId
  if (p.parserId !== undefined) form.parserId = p.parserId || ''
}

function applyPrefs() {
  const p = readPrefs()
  if (!p) return
  if (p.devIndex != null) form.devIndex = Number(p.devIndex)
  if (p.canIndex != null) form.canIndex = Number(p.canIndex)
  if (!props.lockBaud && p.baudRate != null) {
    form.baudRate = pickOption(Number(p.baudRate), baudOptions, o => o.value, 500)
  }
  if (p.nodeAddrTo != null) form.nodeAddrTo = Number(p.nodeAddrTo)
  // 锁定字段不以本地 prefs 覆盖
  if (!parserLocked.value && p.parserId !== undefined) form.parserId = p.parserId || ''
  if (!assemblerLocked.value && p.assemblerId !== undefined) form.assemblerId = p.assemblerId || ASSEMBLER_CAN_BIU
  if (p.vendor != null) form.vendor = Number(p.vendor)
}

function applyLockedPipeline() {
  if (props.lockBaud) form.baudRate = lockedBaudValue()
  const p = props.preset
  if (!p) return
  if (assemblerLocked.value && p.assemblerId) form.assemblerId = p.assemblerId
  if (parserLocked.value && p.parserId !== undefined) form.parserId = p.parserId || ''
}

function onAssemblerChange(aid) {
  if (parserLocked.value) return
  const suggested = ASSEMBLER_PARSER_DEFAULTS[aid]
  if (suggested) form.parserId = suggested
}

async function loadOpenedChannels() {
  try {
    const res = await listCanChannels()
    const list = res.data || []
    openedChannels.value = (Array.isArray(list) ? list : [])
      .filter(c => c && !c.demo)
      .map(c => ({
        vendor: Number(c.vendor),
        devIndex: Number(c.devIndex),
        canIndex: Number(c.canIndex),
        baudRate: c.baudRate != null ? Number(c.baudRate) : null,
        deviceId: c.deviceId
      }))
  } catch {
    openedChannels.value = []
  }
}

async function loadParsers() {
  try {
    const res = await listParsers()
    const list = res.data?.parsers || res.data || []
    parserOptions.value = Array.isArray(list)
      ? list.map(p =>
          typeof p === 'string'
            ? { id: p, name: p }
            : { id: p.id || p.parserId, name: p.name || p.label || p.id || p.parserId }
        )
      : []
  } catch {
    parserOptions.value = FALLBACK_PARSERS_CAN
  }
}

async function loadAssemblers() {
  try {
    const res = await listAssemblers('can')
    const list = res.data?.assemblers || res.data || []
    assemblerOptions.value = Array.isArray(list)
      ? list.map(a =>
          typeof a === 'string'
            ? { id: a, name: a }
            : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
        )
      : []
  } catch {
    assemblerOptions.value = FALLBACK_ASSEMBLERS_CAN
  }
  if (assemblerLocked.value) {
    applyLockedPipeline()
  } else if (!assemblerOptions.value.some(a => a.id === form.assemblerId)) {
    form.assemblerId = assemblerOptions.value[0]?.id || ASSEMBLER_CAN_BIU
  }
}

async function refreshVendors() {
  refreshing.value = true
  try {
    const [vendorRes] = await Promise.all([listCanVendors(), loadOpenedChannels()])
    const list = mapVendors(vendorRes.data?.vendors || vendorRes.data || [])
    vendors.value = list
    vendorSelectKey.value += 1
    const saved = readPrefs()?.vendor
    if (saved != null && list.some(v => v.value === Number(saved))) {
      form.vendor = Number(saved)
    } else if (form.vendor == null || !list.some(v => v.value === form.vendor)) {
      form.vendor = pickDefaultVendor(list)
    }
    clampCanIndex()
    clampDevIndex()
  } finally {
    refreshing.value = false
  }
}

async function onOpened() {
  applyPrefs()
  applyPreset(props.preset)
  applyLockedPipeline()
  await Promise.all([loadParsers(), loadAssemblers(), refreshVendors()])
  applyLockedPipeline()
  clampCanIndex()
  clampDevIndex()
}

async function submit() {
  if (form.vendor == null || opening.value) return
  clampCanIndex()
  clampDevIndex()
  if (selectedChannelDisabled.value) {
    ElMessage.warning('该通道已打开且波特率不符，请选择其他通道')
    return
  }
  if (props.lockBaud) form.baudRate = LOCKED_BAUD
  opening.value = true
  try {
    const payload = {
      vendor: form.vendor,
      devIndex: form.devIndex,
      canIndex: form.canIndex,
      baudRate: form.baudRate,
      nodeAddrTo: form.nodeAddrTo,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || ASSEMBLER_CAN_BIU,
      source: props.source,
      fullDuplex: props.preset?.fullDuplex === true
    }
    // 首页不传 cableFlag；遥控 A/B 由 props 指定 0/1
    if (props.cableFlag != null && Number.isFinite(Number(props.cableFlag))) {
      payload.cableFlag = Number(props.cableFlag)
    }
    const res = await openCanChannel(payload)
    const deviceId = res.data?.deviceId
    if (deviceId) setActiveDevice('can', deviceId)
    writePrefs({
      vendor: form.vendor,
      devIndex: form.devIndex,
      canIndex: form.canIndex,
      baudRate: form.baudRate,
      nodeAddrTo: form.nodeAddrTo,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || ASSEMBLER_CAN_BIU
    })
    const reused = res.data?.status === 'already_open'
    ElMessage.success(reused ? '已使用现有can卡并绑定本页参数' : 'CAN 通道已打开')
    onVisibleChange(false)
    emit('success', { response: res, deviceId, reused })
  } finally {
    opening.value = false
  }
}

watch(
  () => props.modelValue,
  v => {
    if (!v) return
    applyPrefs()
  }
)

watch(
  () => form.vendor,
  () => {
    clampCanIndex()
    clampDevIndex()
  }
)
</script>

<style scoped>
.dlg-title {
  display: block;
  padding-left: 0;
  font-size: var(--el-dialog-title-font-size, 16px);
  line-height: 1.5;
  color: var(--el-text-color-primary);
}
.port-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.conn-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}
.conn-ctrl {
  width: 240px !important;
}
.conn-ctrl :deep(.el-select__selected-item),
.conn-ctrl :deep(.el-select__placeholder) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.field-tip {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
.label-tip {
  margin-left: 4px;
  vertical-align: middle;
  cursor: help;
  color: var(--el-text-color-secondary);
}
</style>

<style>
.can-connect-dialog.el-dialog .el-dialog__header {
  padding: 16px 20px 8px;
  margin-right: 0;
}
.can-connect-dialog.el-dialog .el-dialog__body {
  padding: 8px 20px 20px;
}
.can-connect-dialog.el-dialog .el-dialog__headerbtn {
  top: 16px;
  right: 16px;
}
</style>
