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
              v-for="v in vendors"
              :key="`${v.value}-${v.name}`"
              :label="formatVendorLabel(v)"
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
        <el-select v-model="form.devIndex" :disabled="opening" class="conn-ctrl">
          <el-option :label="'0'" :value="0" />
        </el-select>
      </el-form-item>
      <el-form-item label="通道号">
        <el-select v-model="form.canIndex" :disabled="opening" class="conn-ctrl">
          <el-option v-for="ch in canIndexOptions" :key="ch.value" :label="ch.label" :value="ch.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="波特率">
        <el-select v-model="form.baudRate" :disabled="opening" class="conn-ctrl">
          <el-option v-for="b in baudOptions" :key="b.value" :label="b.label" :value="b.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="线缆">
        <el-select v-model="form.cableFlag" :disabled="opening" class="conn-ctrl">
          <el-option v-for="c in cableOptions" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标地址">
        <el-select v-model="form.nodeAddrTo" :disabled="opening" class="conn-ctrl">
          <el-option v-for="n in nodeAddrOptions" :key="n.value" :label="n.label" :value="n.value" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <template #label>
          组装器
          <el-tooltip :content="ASSEMBLER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select v-model="form.assemblerId" clearable placeholder="默认透传" class="conn-ctrl" :disabled="opening">
          <el-option v-for="a in assemblerOptions" :key="a.id" :label="a.name" :value="a.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">CAN 帧组装多在库内完成；此处默认透传</div>
      </el-form-item>
      <el-form-item>
        <template #label>
          解释器
          <el-tooltip :content="PARSER_TIP" placement="top">
            <el-icon class="label-tip"><question-filled /></el-icon>
          </el-tooltip>
        </template>
        <el-select v-model="form.parserId" clearable placeholder="请选择解释器" class="conn-ctrl" :disabled="opening">
          <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <div v-if="showBindingTips" class="field-tip">不绑定则不解析数据</div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="opening" :disabled="form.vendor == null" @click="submit">打开</el-button>
        <el-button @click="onVisibleChange(false)">取消</el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listCanVendors, listParsers, listAssemblers, openCanChannel } from '@/api/payload/device'
import { setActiveDevice } from '@/utils/deviceSnapshotCache'
import { ASSEMBLER_TIP, PARSER_TIP } from '@/utils/pipelineTips'

const canIndexOptions = [
  { value: 0, label: '0' },
  { value: 1, label: '1' }
]
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
const cableOptions = [
  { value: 0, label: '0 = 线A' },
  { value: 1, label: '1 = 线B' }
]
const nodeAddrOptions = [
  { value: 0x0d, label: '0x0D = 激光终端A' },
  { value: 0x0e, label: '0x0E = 激光终端B' }
]

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '新建 CAN 连接' },
  source: { type: String, default: 'home' },
  prefsKey: { type: String, default: 'payload:control:canPrefs' },
  showBindingTips: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'success'])

const form = reactive({
  vendor: null,
  devIndex: 0,
  canIndex: 0,
  baudRate: 500,
  nodeAddrTo: 0x0d,
  cableFlag: 0,
  assemblerId: 'passthrough',
  parserId: 'tm_can_yc'
})

const opening = ref(false)
const refreshing = ref(false)
const vendorSelectKey = ref(0)
const vendors = ref([])
const parserOptions = ref([])
const assemblerOptions = ref([])

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

function formatVendorLabel(v) {
  return `${v.value} - ${v.name || ''}`
}

function isPcieVendor(v) {
  return `${v.key || ''} ${v.name || ''}`.toUpperCase().includes('PCIE')
}

function pickDefaultVendor(list) {
  if (!list.length) return null
  return (list.find(isPcieVendor) || list[0]).value
}

function mapVendors(raw) {
  return (raw || []).map(v => ({ value: v.value, key: v.key, name: v.name }))
}

function applyPrefs() {
  const p = readPrefs()
  if (!p) return
  if (p.devIndex != null) form.devIndex = Number(p.devIndex)
  if (p.canIndex != null) form.canIndex = Number(p.canIndex)
  if (p.baudRate != null) form.baudRate = pickOption(Number(p.baudRate), baudOptions, o => o.value, 500)
  if (p.cableFlag != null) form.cableFlag = pickOption(Number(p.cableFlag), cableOptions, o => o.value, 0)
  if (p.nodeAddrTo != null) form.nodeAddrTo = pickOption(Number(p.nodeAddrTo), nodeAddrOptions, o => o.value, 0x0d)
  if (p.parserId !== undefined) form.parserId = p.parserId || ''
  if (p.assemblerId !== undefined) form.assemblerId = p.assemblerId || 'passthrough'
  if (p.vendor != null) form.vendor = Number(p.vendor)
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
    parserOptions.value = [{ id: 'tm_can_yc', name: 'CAN遥测复合帧' }]
  }
}

async function loadAssemblers() {
  try {
    const res = await listAssemblers()
    const list = res.data?.assemblers || res.data || []
    assemblerOptions.value = Array.isArray(list)
      ? list.map(a =>
          typeof a === 'string'
            ? { id: a, name: a }
            : { id: a.id || a.assemblerId, name: a.name || a.label || a.id || a.assemblerId }
        )
      : []
  } catch {
    assemblerOptions.value = [
      { id: 'passthrough', name: '透传（默认）' },
      { id: 'eng_tm_subpkt', name: '工程遥测子包组装' }
    ]
  }
}

async function refreshVendors() {
  refreshing.value = true
  try {
    const res = await listCanVendors()
    const list = mapVendors(res.data?.vendors || res.data || [])
    vendors.value = list
    vendorSelectKey.value += 1
    const saved = readPrefs()?.vendor
    if (saved != null && list.some(v => v.value === Number(saved))) {
      form.vendor = Number(saved)
    } else if (form.vendor == null || !list.some(v => v.value === form.vendor)) {
      form.vendor = pickDefaultVendor(list)
    }
  } finally {
    refreshing.value = false
  }
}

async function onOpened() {
  applyPrefs()
  await Promise.all([loadParsers(), loadAssemblers(), refreshVendors()])
}

async function submit() {
  if (form.vendor == null || opening.value) return
  opening.value = true
  try {
    const res = await openCanChannel({
      vendor: form.vendor,
      devIndex: form.devIndex,
      canIndex: form.canIndex,
      baudRate: form.baudRate,
      nodeAddrTo: form.nodeAddrTo,
      cableFlag: form.cableFlag,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || 'passthrough',
      source: props.source
    })
    const deviceId = res.data?.deviceId
    if (deviceId) setActiveDevice('can', deviceId)
    writePrefs({
      vendor: form.vendor,
      devIndex: form.devIndex,
      canIndex: form.canIndex,
      baudRate: form.baudRate,
      cableFlag: form.cableFlag,
      nodeAddrTo: form.nodeAddrTo,
      parserId: form.parserId || '',
      assemblerId: form.assemblerId || 'passthrough'
    })
    if (res.data?.status === 'already_open') {
      ElMessage.error('设备已打开')
      return
    }
    ElMessage.success('CAN 通道已打开')
    onVisibleChange(false)
    emit('success', { response: res, deviceId })
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
