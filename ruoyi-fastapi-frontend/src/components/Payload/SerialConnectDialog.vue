<template>
  <el-dialog
    :model-value="modelValue"
    width="560px"
    destroy-on-close
    class="serial-connect-dialog"
    @update:model-value="onVisibleChange"
    @opened="onOpened"
  >
    <template #header>
      <span class="dlg-title">{{ title }}</span>
    </template>
    <el-form label-width="100px" class="conn-form">
      <el-form-item label="串口号">
        <div class="ctrl-col">
          <el-select
            v-model="form.port"
            filterable
            :disabled="opening"
            class="conn-ctrl"
            @change="onPortChange"
          >
            <el-option
              v-for="p in portOptions"
              :key="p.port"
              :label="p.label"
              :value="p.port"
              :disabled="p.disabled"
            />
          </el-select>
        </div>
        <div class="action-col">
          <el-button
            type="primary"
            plain
            :loading="refreshing"
            :disabled="opening"
            @click="refreshPorts"
          >刷新</el-button>
        </div>
      </el-form-item>
      <el-form-item label="波特率">
        <div class="ctrl-col">
          <el-select
            v-model="form.baudChoice"
            :disabled="baudDisabled"
            class="conn-ctrl"
            @change="onBaudChoiceChange"
          >
            <el-option v-for="b in activeBaudChoices" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
          <el-input-number
            v-if="isFree && form.baudChoice === 'custom'"
            v-model="form.baudrate"
            :disabled="opening"
            :min="110"
            :step="100"
            class="conn-ctrl conn-ctrl--gap"
          />
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item label="数据位">
        <div class="ctrl-col">
          <el-select v-model="form.dataBits" :disabled="paramsLocked" class="conn-ctrl">
            <el-option v-for="d in dataBitsOptions" :key="d" :label="String(d)" :value="d" />
          </el-select>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item label="停止位">
        <div class="ctrl-col">
          <el-select v-model="form.stopBits" :disabled="paramsLocked" class="conn-ctrl">
            <el-option v-for="s in stopBitsOptions" :key="s" :label="String(s)" :value="s" />
          </el-select>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item label="校验位">
        <div class="ctrl-col">
          <el-select v-model="form.parity" :disabled="paramsLocked" class="conn-ctrl">
            <el-option v-for="p in parityOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item label="流控制">
        <div class="ctrl-col">
          <el-select v-model="form.flowControl" :disabled="paramsLocked" class="conn-ctrl">
            <el-option v-for="f in flowOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item>
        <template #label>
          组装器
          <el-tooltip :content="ASSEMBLER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <div class="ctrl-col">
          <el-select
            v-model="form.assemblerId"
            :clearable="isFree"
            :placeholder="isFree ? '默认透传' : undefined"
            :disabled="bindingLocked"
            class="conn-ctrl"
          >
            <el-option v-for="a in assemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
          <div v-if="showBindingTips" class="field-tip">拆分包需选对应组装器；默认透传</div>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item>
        <template #label>
          解释器
          <el-tooltip :content="PARSER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <div class="ctrl-col">
          <el-select
            v-model="form.parserId"
            clearable
            :placeholder="isFree ? '请选择解释器' : '不绑定'"
            :disabled="bindingLocked"
            class="conn-ctrl"
          >
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div v-if="showBindingTips" class="field-tip">不绑定则不解析数据</div>
        </div>
        <div class="action-col" />
      </el-form-item>
      <el-form-item>
        <div class="ctrl-col footer-actions">
          <el-button
            type="primary"
            :loading="opening"
            :disabled="!form.port || selectedPortDisabled"
            @click="submit"
          >{{ confirmLabel }}</el-button>
          <el-button @click="onVisibleChange(false)">取消</el-button>
        </div>
        <div class="action-col" />
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { openSerialPort, getDeviceSnapshot } from '@/api/payload/device'
import { takeDeviceSnapshot, SNAPSHOT_TTL_MS } from '@/utils/deviceSnapshotCache'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'

const FREE_BAUD_CHOICES = [
  110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200, 128000, 230400,
  256000, 460800, 921600, 1000000, 2000000
]
  .map(v => ({ value: v, label: String(v) }))
  .concat([{ value: 'custom', label: 'Customize' }])

const FREE_DATA_BITS = [5, 6, 7, 8]
const FREE_STOP_BITS = [1, 1.5, 2]
const PARITY_OPTIONS = [
  { value: 'N', label: 'NONE' },
  { value: 'E', label: 'EVEN' },
  { value: 'O', label: 'ODD' },
  { value: 'M', label: 'MARK' },
  { value: 'S', label: 'SPACE' }
]
const FLOW_OPTIONS = [
  { value: 'NONE', label: 'NONE' },
  { value: 'XON/XOFF', label: 'XON/XOFF' },
  { value: 'RTS/CTS', label: 'RTS/CTS' },
  { value: 'DTR/DSR', label: 'DTR/DSR' },
  { value: 'RTS/CTS/XON/XOFF', label: 'RTS/CTS/XON/XOFF' },
  { value: 'DTR/DSR/XON/XOFF', label: 'DTR/DSR/XON/XOFF' }
]

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '新建串口连接' },
  /** 绑定页面 id：home / camera_ctrl / camera_image / rkdj / zk … */
  source: { type: String, required: true },
  /** free=首页可改物理参数且禁止选已开串口；preset=单板页参数受限、可复用匹配串口 */
  mode: { type: String, default: 'preset', validator: v => ['free', 'preset'].includes(v) },
  /** preset 模式的固定参数 */
  preset: {
    type: Object,
    default: () => ({
      baudChoice: 115200,
      baudrate: 115200,
      dataBits: 8,
      stopBits: 1,
      parity: 'N',
      flowControl: 'NONE',
      assemblerId: 'passthrough',
      parserId: ''
    })
  },
  /** preset 波特率下拉；free 模式忽略 */
  baudChoices: { type: Array, default: null },
  /** preset 下未复用时是否允许改波特率（如相机图像） */
  baudEditable: { type: Boolean, default: false },
  /** exact=与 preset 波特率一致；allowlist=波特率在 baudChoices 内即可 */
  matchBaudMode: {
    type: String,
    default: 'exact',
    validator: v => ['exact', 'allowlist'].includes(v)
  },
  preferredPort: { type: String, default: '' },
  prefsKey: { type: String, default: '' },
  fallbackParsers: { type: Array, default: () => [] },
  fallbackAssemblers: { type: Array, default: () => [] },
  showBindingTips: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'success'])

const isFree = computed(() => props.mode === 'free')

const form = reactive({
  port: '',
  baudChoice: 9600,
  baudrate: 9600,
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE',
  assemblerId: 'passthrough',
  parserId: ''
})

const opening = ref(false)
const refreshing = ref(false)
const serialPorts = ref([])
const openedPortMap = ref(new Map())
const parserOptions = ref([])
const assemblerOptions = ref([])

const dataBitsOptions = computed(() => (isFree.value ? FREE_DATA_BITS : [Number(props.preset.dataBits) || 8]))
const stopBitsOptions = computed(() => (isFree.value ? FREE_STOP_BITS : [Number(props.preset.stopBits) || 1]))
const parityOptions = PARITY_OPTIONS
const flowOptions = computed(() => (isFree.value ? FLOW_OPTIONS : FLOW_OPTIONS.slice(0, 4)))

const activeBaudChoices = computed(() => {
  if (isFree.value) return FREE_BAUD_CHOICES
  if (Array.isArray(props.baudChoices) && props.baudChoices.length) return props.baudChoices
  const baud = Number(props.preset.baudChoice || props.preset.baudrate) || 115200
  return [{ value: baud, label: String(baud) }]
})

const allowBaudList = computed(() =>
  activeBaudChoices.value.map(b => Number(b.value)).filter(n => Number.isFinite(n))
)

function normParity(v) {
  const s = String(v || 'N').trim().toUpperCase()
  if (s === 'NONE') return 'N'
  if (s === 'EVEN') return 'E'
  if (s === 'ODD') return 'O'
  if (s === 'MARK') return 'M'
  if (s === 'SPACE') return 'S'
  return s.slice(0, 1) || 'N'
}

function normFlow(v) {
  const s = String(v || 'NONE').trim().toUpperCase().replace(/[\s_-]/g, '')
  if (!s || s === 'NONE' || s === 'NO') return 'NONE'
  if (s.includes('XON') && s.includes('RTS')) return 'RTS/CTS/XON/XOFF'
  if (s.includes('XON') && s.includes('DTR')) return 'DTR/DSR/XON/XOFF'
  if (s.includes('XON')) return 'XON/XOFF'
  if (s.includes('RTS')) return 'RTS/CTS'
  if (s.includes('DTR')) return 'DTR/DSR'
  return s
}

function applyOpenedPorts(list) {
  const map = new Map()
  for (const p of list || []) {
    if (p?.alive === false) continue
    const port = String(p?.port || '').trim()
    if (!port) continue
    map.set(port.toUpperCase(), { ...p, port })
  }
  openedPortMap.value = map
}

function getOpenedInfo(port) {
  if (!port) return null
  return openedPortMap.value.get(String(port).toUpperCase()) || null
}

function serialParamsMatch(opened) {
  if (!opened || isFree.value) return false
  const baud = Number(opened.baudrate)
  if (!Number.isFinite(baud)) return false
  if (props.matchBaudMode === 'allowlist') {
    if (!allowBaudList.value.includes(baud)) return false
  } else {
    const needBaud = Number(props.preset.baudChoice || props.preset.baudrate)
    if (baud !== needBaud) return false
  }
  if (Number(opened.dataBits) !== Number(props.preset.dataBits)) return false
  if (Number(opened.stopBits) !== Number(props.preset.stopBits)) return false
  if (normParity(opened.parity) !== normParity(props.preset.parity)) return false
  if (normFlow(opened.flowControl) !== normFlow(props.preset.flowControl)) return false
  return true
}

const portOptions = computed(() =>
  (serialPorts.value || []).map(p => {
    const port = p?.port || ''
    const base = p?.description ? `${port} (${p.description})` : port
    const opened = getOpenedInfo(port)
    if (!opened) {
      return { port, label: base, disabled: false, reusable: false }
    }
    if (isFree.value) {
      return { port, label: `${base} - 已连接`, disabled: true, reusable: false }
    }
    const match = serialParamsMatch(opened)
    return {
      port,
      label: match ? `${base} - 已连接` : `${base} - 已连接 - 连接参数不符`,
      disabled: !match,
      reusable: match
    }
  })
)

const canReuseSelectedPort = computed(() => {
  if (isFree.value || !form.port) return false
  return serialParamsMatch(getOpenedInfo(form.port))
})

const selectedPortDisabled = computed(() => {
  const hit = portOptions.value.find(p => p.port === form.port)
  return !!hit?.disabled
})

const paramsLocked = computed(() => {
  if (opening.value) return true
  if (isFree.value) return false
  return true
})

const bindingLocked = computed(() => {
  if (opening.value) return true
  return !isFree.value
})

const baudDisabled = computed(() => {
  if (opening.value) return true
  if (isFree.value) return false
  if (canReuseSelectedPort.value) return true
  return !props.baudEditable
})

const confirmLabel = computed(() => (canReuseSelectedPort.value ? '使用' : '打开'))

function pickOption(saved, options, getValue, fallback) {
  const list = options || []
  if (saved == null || saved === '') return fallback
  return list.some(o => getValue(o) === saved) ? saved : fallback
}

function readPrefs() {
  if (!props.prefsKey) return null
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
  if (!props.prefsKey) return
  try {
    localStorage.setItem(props.prefsKey, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

function applyOptionsFromSnapshot(data) {
  const plist = data?.parsers || []
  if (Array.isArray(plist) && plist.length) {
    parserOptions.value = plist.map(p =>
      typeof p === 'string' ? { id: p, name: p } : { id: p.id || p.parserId, name: p.name || p.id }
    )
  }
  const alist = data?.assemblers || []
  if (Array.isArray(alist) && alist.length) {
    assemblerOptions.value = alist.map(a =>
      typeof a === 'string' ? { id: a, name: a } : { id: a.id || a.assemblerId, name: a.name || a.id }
    )
  }
}

function ensureFallbacks() {
  if (!parserOptions.value.length && props.fallbackParsers.length) {
    parserOptions.value = [...props.fallbackParsers]
  }
  if (!assemblerOptions.value.length && props.fallbackAssemblers.length) {
    assemblerOptions.value = [...props.fallbackAssemblers]
  }
  if (!assemblerOptions.value.length) {
    assemblerOptions.value = [{ id: 'passthrough', name: '透传（默认）' }]
  }
}

function applyPresetFields({ resetBaud = true } = {}) {
  const preset = props.preset || {}
  if (resetBaud) {
    form.baudChoice = preset.baudChoice ?? preset.baudrate ?? 115200
    form.baudrate = Number(preset.baudrate ?? preset.baudChoice) || 115200
  } else if (props.matchBaudMode === 'allowlist') {
    const cur = Number(form.baudChoice || form.baudrate)
    if (!allowBaudList.value.includes(cur)) {
      form.baudChoice = preset.baudChoice ?? preset.baudrate
      form.baudrate = Number(preset.baudrate ?? preset.baudChoice) || 115200
    }
  } else {
    form.baudChoice = preset.baudChoice ?? preset.baudrate
    form.baudrate = Number(preset.baudrate ?? preset.baudChoice) || 115200
  }
  form.dataBits = preset.dataBits ?? 8
  form.stopBits = preset.stopBits ?? 1
  form.parity = preset.parity || 'N'
  form.flowControl = preset.flowControl || 'NONE'
  form.assemblerId = preset.assemblerId || 'passthrough'
  form.parserId = preset.parserId || ''
}

function applyPortSelection(port, { resetBaud = true } = {}) {
  if (isFree.value) return
  const opened = getOpenedInfo(port)
  const reusable = serialParamsMatch(opened)
  if (reusable && opened) {
    const baud = Number(opened.baudrate)
    form.baudChoice = baud
    form.baudrate = baud
    form.dataBits = Number(opened.dataBits)
    form.stopBits = Number(opened.stopBits)
    form.parity = normParity(opened.parity)
    form.flowControl = normFlow(opened.flowControl)
    form.assemblerId = props.preset.assemblerId || 'passthrough'
    form.parserId = props.preset.parserId || ''
    return
  }
  applyPresetFields({ resetBaud })
}

function pickDefaultPort(preferred) {
  const options = portOptions.value
  // 原逻辑：偏好口（可选）→ 首个可选
  let port = ''
  if (preferred && options.some(p => p.port === preferred && !p.disabled)) {
    port = preferred
  } else {
    port = options.find(p => !p.disabled)?.port || ''
  }
  // 原结果已连接，且仍有未连接口 → 改选未连接
  const freePorts = options.filter(p => !p.disabled && !getOpenedInfo(p.port))
  if (freePorts.length && (!port || getOpenedInfo(port))) {
    return freePorts[0].port
  }
  return port
}

function ensurePortSelectable() {
  if (!form.port) return
  const hit = portOptions.value.find(p => p.port === form.port)
  if (hit?.disabled) {
    form.port = pickDefaultPort('')
    applyPortSelection(form.port)
  }
}

function syncSelectedPort() {
  if (!serialPorts.value.length) {
    form.port = ''
    return
  }
  if (!form.port || !serialPorts.value.some(p => p.port === form.port)) {
    form.port = pickDefaultPort(props.preferredPort || '')
    applyPortSelection(form.port)
    return
  }
  // 当前选中已连接，但还有未连接 → 改选未连接
  if (getOpenedInfo(form.port)) {
    const free = portOptions.value.find(p => !p.disabled && !getOpenedInfo(p.port))
    if (free) {
      form.port = free.port
      applyPortSelection(form.port)
      return
    }
  }
  ensurePortSelectable()
}

function applyFreePrefs() {
  const p = readPrefs()
  if (!p) {
    form.baudChoice = 9600
    form.baudrate = 9600
    form.dataBits = 8
    form.stopBits = 1
    form.parity = 'N'
    form.flowControl = 'NONE'
    form.assemblerId = 'passthrough'
    form.parserId = ''
    return
  }
  if (p.port) form.port = String(p.port)
  if (p.baudChoice !== undefined && p.baudChoice !== null) {
    const choice = p.baudChoice === 'custom' ? 'custom' : Number(p.baudChoice)
    form.baudChoice = pickOption(choice, FREE_BAUD_CHOICES, o => o.value, 9600)
  }
  if (p.baudrate != null) form.baudrate = Number(p.baudrate) || 9600
  if (p.dataBits != null) {
    form.dataBits = pickOption(Number(p.dataBits), FREE_DATA_BITS.map(d => ({ value: d })), o => o.value, 8)
  }
  if (p.stopBits != null) {
    form.stopBits = pickOption(Number(p.stopBits), FREE_STOP_BITS.map(s => ({ value: s })), o => o.value, 1)
  }
  if (p.parity) form.parity = pickOption(String(p.parity), PARITY_OPTIONS, o => o.value, 'N')
  if (p.flowControl) form.flowControl = pickOption(String(p.flowControl), FLOW_OPTIONS, o => o.value, 'NONE')
  if (p.parserId !== undefined) form.parserId = p.parserId || ''
  if (p.assemblerId !== undefined) form.assemblerId = p.assemblerId || 'passthrough'
}

function resetFormForOpen() {
  if (isFree.value) {
    applyFreePrefs()
    syncSelectedPort()
    return
  }
  applyPresetFields({ resetBaud: true })
  form.port = pickDefaultPort(props.preferredPort || '')
  applyPortSelection(form.port)
}

function onPortChange(port) {
  applyPortSelection(port)
}

function onBaudChoiceChange(v) {
  if (v === 'custom') return
  const baud = Number(v)
  form.baudChoice = baud
  form.baudrate = baud
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

function applyMetaData(data) {
  serialPorts.value = data?.serialList || []
  applyOpenedPorts(data?.serialOpened)
  applyOptionsFromSnapshot(data || {})
  ensureFallbacks()
  syncSelectedPort()
}

async function refreshPorts() {
  refreshing.value = true
  try {
    const res = await getDeviceSnapshot(['serialList', 'serialOpened'])
    serialPorts.value = res.data?.serialList || []
    applyOpenedPorts(res.data?.serialOpened)
    syncSelectedPort()
  } finally {
    refreshing.value = false
  }
}

async function loadMeta() {
  const cached = takeDeviceSnapshot({ maxAgeMs: SNAPSHOT_TTL_MS, consume: false })
  if (cached && (cached.serialList || cached.serialOpened)) {
    applyMetaData(cached)
    // 后台刷新，不挡首次展示
    getDeviceSnapshot(['serialList', 'serialOpened', 'parsers', 'assemblers'])
      .then(res => {
        applyMetaData(res.data || {})
      })
      .catch(() => {})
    return
  }
  refreshing.value = true
  try {
    const res = await getDeviceSnapshot(['serialList', 'serialOpened', 'parsers', 'assemblers'])
    applyMetaData(res.data || {})
  } catch {
    ensureFallbacks()
  } finally {
    refreshing.value = false
  }
}

async function onOpened() {
  // 打开时由 watch(modelValue) 拉取最新串口列表；此处再同步选中项
  syncSelectedPort()
}

async function submit() {
  if (!form.port || opening.value || selectedPortDisabled.value) return
  if (isFree.value && form.baudChoice !== 'custom') {
    form.baudrate = Number(form.baudChoice)
  }
  opening.value = true
  try {
    const reuse = canReuseSelectedPort.value
    const opened = getOpenedInfo(form.port)
    let baud = form.baudChoice === 'custom' ? Number(form.baudrate) : Number(form.baudChoice) || form.baudrate
    if (reuse && opened && Number.isFinite(Number(opened.baudrate))) {
      baud = Number(opened.baudrate)
      form.baudChoice = baud
      form.baudrate = baud
    }
    const res = await openSerialPort({
      port: form.port,
      baudrate: baud,
      dataBits: form.dataBits,
      stopBits: form.stopBits,
      parity: form.parity,
      flowControl: form.flowControl,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || 'passthrough',
      source: props.source
    })

    if (isFree.value) {
      writePrefs({
        port: form.port,
        baudChoice: form.baudChoice,
        baudrate: form.baudrate,
        dataBits: form.dataBits,
        stopBits: form.stopBits,
        parity: form.parity,
        flowControl: form.flowControl,
        parserId: form.parserId || '',
        assemblerId: form.assemblerId || 'passthrough'
      })
      if (res.data?.status === 'already_open') {
        ElMessage.error('设备已打开')
        return
      }
      ElMessage.success('串口已打开')
    } else {
      const reused = reuse || res.data?.status === 'already_open'
      ElMessage.success(reused ? '已使用现有串口并绑定本页参数' : '串口已打开')
    }

    emit('success', {
      port: form.port,
      reused: reuse || res.data?.status === 'already_open',
      response: res,
      form: { ...form, baudrate: baud }
    })
    onVisibleChange(false)
  } catch (e) {
    ElMessage.error(e?.message || '打开串口失败')
  } finally {
    opening.value = false
  }
}

watch(
  () => props.modelValue,
  async v => {
    if (!v) return
    // 每次打开都拉最新已开串口状态（避免控制串口打开后图像弹窗仍显示旧状态）
    openedPortMap.value = new Map()
    resetFormForOpen()
    await loadMeta()
    resetFormForOpen()
  }
)
</script>

<style scoped>
.dlg-title {
  display: block;
  /* 与下方表单项 label 列左缘对齐：body 左右 padding 由 dialog 统一 */
  padding-left: 0;
  font-size: var(--el-dialog-title-font-size, 16px);
  line-height: 1.5;
  color: var(--el-text-color-primary);
}
.conn-form :deep(.el-form-item__content) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px;
  column-gap: 8px;
  align-items: start;
  width: 100%;
}
.ctrl-col {
  grid-column: 1;
  min-width: 0;
  width: 100%;
}
.action-col {
  grid-column: 2;
  display: flex;
  justify-content: stretch;
}
.action-col :deep(.el-button) {
  width: 100%;
}
.conn-ctrl {
  width: 100% !important;
  max-width: 100%;
}
.conn-ctrl--gap {
  margin-top: 8px;
}
.conn-ctrl.el-input-number :deep(.el-input__inner) {
  text-align: left;
}
.conn-ctrl :deep(.el-select__selected-item),
.conn-ctrl :deep(.el-select__placeholder) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.footer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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
/* 标题与表单 label 左缘对齐：header/body 同左右内边距 */
.serial-connect-dialog.el-dialog .el-dialog__header {
  padding: 16px 20px 8px;
  margin-right: 0;
}
.serial-connect-dialog.el-dialog .el-dialog__body {
  padding: 8px 20px 20px;
}
.serial-connect-dialog.el-dialog .el-dialog__headerbtn {
  top: 16px;
  right: 16px;
}
</style>
