<template>
  <div class="app-container xl-board-page">
    <div class="main-grid">
      <div class="col-left">
        <el-form :inline="true" class="left-toolbar" size="small">
          <el-form-item>
            <el-button
              v-if="!serialConnected"
              type="primary"
              size="small"
              @click="openSerialDialog"
            >新建串口连接</el-button>
            <el-button
              v-else
              type="success"
              plain
              size="small"
              class="btn-connected"
              @click="closeSerial"
            >关闭串口 · {{ serialPort }}</el-button>
          </el-form-item>
        </el-form>

        <div class="panel panel-tc">
          <div class="panel-head">
            <span class="panel-title">遥控</span>
            <el-button class="export-tc-btn" link type="primary" @click="exportPreviewOrders">导出</el-button>
            <el-input
              v-model="filterText"
              clearable
              size="small"
              placeholder="搜索指令代号/名称/参数标题（空格分词）"
              class="filter-input"
            />
          </div>
          <el-scrollbar class="panel-body">
            <div v-if="filteredOrders.length" class="order-list">
              <div v-for="ord in filteredOrders" :key="ord.id" class="order-card">
                <div class="order-title">
                  {{ ord.id }} - {{ ord.name }} - {{ orderByteLen(ord) }} 字节
                </div>
                <div class="order-desc mb8">
                  <el-descriptions :column="1" border size="small" label-width="100px" class="order-desc-hex">
                    <el-descriptions-item label="指令参数">
                      {{ assembledMap[ord.id]?.hex || '-' }}
                    </el-descriptions-item>
                  </el-descriptions>
                </div>
                <el-form label-width="140px" size="small" class="order-form">
                  <template v-for="(comp, idx) in ord.component || []" :key="`${ord.id}-${idx}`">
                    <el-form-item
                      v-if="compType(comp) !== 'fixed'"
                      :label="comp.title || `参数${idx + 1}`"
                    >
                      <el-input-number
                        v-if="compType(comp) === 'number'"
                        v-model="compValues[ord.id][idx]"
                        class="comp-field"
                        :min="numBound(comp.minVal)"
                        :max="numBound(comp.maxVal)"
                        :precision="numberPrecision(comp)"
                        :step="numberStep(comp)"
                        @change="() => previewOrder(ord, { showLoading: false })"
                      />
                      <el-select
                        v-else-if="compType(comp) === 'select'"
                        v-model="compValues[ord.id][idx]"
                        class="comp-field"
                        @change="() => previewOrder(ord, { showLoading: false })"
                      >
                        <el-option
                          v-for="(label, key) in comp.options || {}"
                          :key="key"
                          :label="`${key} ${label}`"
                          :value="key"
                        />
                      </el-select>
                      <el-input
                        v-else
                        v-model="compValues[ord.id][idx]"
                        class="comp-field"
                        @change="() => previewOrder(ord, { showLoading: false })"
                      />
                    </el-form-item>
                  </template>
                  <el-form-item>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="previewingId === ord.id"
                      @click="previewOrder(ord)"
                    >预览组帧</el-button>
                    <el-button
                      type="success"
                      size="small"
                      :loading="sendingId === ord.id"
                      :disabled="!serialConnected"
                      @click="sendOrder(ord)"
                    >发送指令</el-button>
                  </el-form-item>
                </el-form>
              </div>
            </div>
            <el-empty v-else description="无匹配指令" :image-size="64" />
          </el-scrollbar>
        </div>

        <div class="panel panel-xfer">
          <PayloadTransferInfo
            v-model="xferDeviceId"
            title="传输信息"
            :devices="xferDevices"
          />
        </div>
      </div>

      <div class="col-right">
        <div class="panel panel-tm">
          <PayloadTelemetryTable level="t3" :types="tmTypes" />
        </div>
      </div>
    </div>

    <SerialConnectDialog
      v-model="serialDlg.visible"
      :source="sourceTag"
      mode="preset"
      :preset="SERIAL_PRESET"
      :baud-choices="serialBaudChoices"
      :preferred-port="serialPort"
      :fallback-parsers="[{ id: 'xl_board_tm', name: 'XL单板遥测' }]"
      :fallback-assemblers="[{ id: 'passthrough', name: '透传（默认）' }]"
      @success="onSerialSuccess"
    />
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { saveAs } from 'file-saver'
import { closeSerialPort, getDeviceSnapshot } from '@/api/payload/device'
import {
  getXlBoardTelecontrolConfig,
  assembleXlBoardTelecontrol,
  sendXlBoardTelecontrol
} from '@/api/payload/xlBoard'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import SerialConnectDialog from '@/components/Payload/SerialConnectDialog.vue'
import { prefetchDeviceSnapshot } from '@/utils/deviceSnapshotCache'
import {
  getDeviceConnectEntry,
  toBaudChoices,
  toSerialPreset
} from '@/utils/deviceConnectDefaults'
import {
  uiDataType,
  isFloatUi,
  numberPrecision,
  numberStep,
  numBound
} from '@/utils/telecontrolComponent'
import { orderMatchesFilter } from '@/utils/telecontrolOrderMatch'

const props = defineProps({
  /** rkdj | zk */
  board: { type: String, required: true },
  /** 页面标题（菜单名） */
  title: { type: String, default: '' }
})

const boardId = computed(() => String(props.board || '').toLowerCase())
const tableKey = computed(() => (boardId.value === 'zk' ? 'ZK' : 'RKDJ'))
const tmTypes = computed(() => [tableKey.value])
const sourceTag = computed(() => boardId.value)
const prefsKey = computed(() => `payload:board:${boardId.value}:prefs`)

const FALLBACK_SERIAL = {
  baudrate: 115200,
  baudChoices: [115200],
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE',
  assemblerId: 'passthrough',
  parserId: 'xl_board_tm'
}
const boardConnectCfg = ref({ ...FALLBACK_SERIAL })
const SERIAL_PRESET = computed(() => toSerialPreset(boardConnectCfg.value))
const serialBaudChoices = computed(() => toBaudChoices(boardConnectCfg.value))

const serialPort = ref('')
const serialConnected = ref(false)
const filterText = ref('')
const rawOrders = ref({})
const orderIds = ref([])
const compValues = reactive({})
const assembledMap = reactive({})
const sendingId = ref('')
const previewingId = ref('')

const xferDeviceId = ref('')

const serialDlg = reactive({ visible: false })

let linkTimer = null
let closingSerial = false

const deviceId = computed(() => (serialPort.value ? `serial:${serialPort.value}` : ''))
/** 传输信息按功能来源聚合 */
const xferSourceId = computed(() => `source:${sourceTag.value}`)
const xferDevices = computed(() => {
  if (serialConnected.value) {
    return [{ id: xferSourceId.value, label: props.title || boardId.value || '本页串口' }]
  }
  return []
})

const filteredOrders = computed(() => {
  const list = orderIds.value.map(id => rawOrders.value[id]).filter(Boolean)
  return list.filter(o => orderMatchesFilter(o, filterText.value))
})

function compType(comp) {
  return String(comp?.componentType || 'fixed').toLowerCase()
}

function orderByteLen(ord) {
  const n = assembledMap[ord.id]?.length
  if (n != null && n > 0) return n
  const hex = assembledMap[ord.id]?.hex
  if (hex) {
    const s = String(hex).replace(/[^0-9A-Fa-f]/g, '')
    return Math.floor(s.length / 2) || '-'
  }
  return '-'
}

function firstSelectOptionKey(comp) {
  const opts = comp?.options || {}
  const keys = Object.keys(opts)
  return keys.length ? keys[0] : ''
}

function initCompValues(orders) {
  for (const [id, ord] of Object.entries(orders || {})) {
    if (!compValues[id]) compValues[id] = {}
    ;(ord.component || []).forEach((comp, idx) => {
      const t = compType(comp)
      if (compValues[id][idx] === undefined) {
        const def = comp.defaultVal
        if (t === 'number') {
          const n = Number(def)
          compValues[id][idx] = Number.isFinite(n) ? n : 0
        } else if (t === 'select') {
          const opts = comp.options || {}
          const defStr = def == null || def === '' ? '' : String(def)
          compValues[id][idx] =
            defStr && Object.prototype.hasOwnProperty.call(opts, defStr)
              ? defStr
              : firstSelectOptionKey(comp)
        } else {
          compValues[id][idx] = def ?? ''
        }
      } else if (t === 'select') {
        // 已有空值时补成第一项，避免下拉不选
        const cur = compValues[id][idx]
        if (cur === '' || cur == null) {
          compValues[id][idx] = firstSelectOptionKey(comp)
        }
      }
    })
  }
}

function valuesForOrder(ord) {
  return (ord.component || []).map((comp, idx) => {
    if (compType(comp) === 'fixed') return comp.defaultVal
    const v = compValues[ord.id]?.[idx]
    if (compType(comp) === 'select') {
      if (v !== undefined && v !== null && v !== '') return v
      const def = comp.defaultVal
      const opts = comp.options || {}
      const defStr = def == null || def === '' ? '' : String(def)
      if (defStr && Object.prototype.hasOwnProperty.call(opts, defStr)) return defStr
      return firstSelectOptionKey(comp)
    }
    return v === undefined || v === null || v === '' ? comp.defaultVal : v
  })
}

function openSerialDialog() {
  serialDlg.visible = true
}

function onSerialSuccess({ port }) {
  applyConnectedState(port)
}

function applyConnectedState(port) {
  serialPort.value = port
  serialConnected.value = true
  xferDeviceId.value = xferSourceId.value
  savePrefs()
}

async function closeSerial() {
  if (!serialPort.value) return
  try {
    await ElMessageBox.confirm(`确认关闭串口「${serialPort.value}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  closingSerial = true
  try {
    await closeSerialPort(serialPort.value)
  } catch (e) {
    ElMessage.error(e?.message || '关闭串口失败')
    closingSerial = false
    return
  }
  serialConnected.value = false
  xferDeviceId.value = ''
  closingSerial = false
  savePrefs()
  ElMessage.success('串口已关闭')
}

async function checkLinkStatus() {
  if (!serialConnected.value || !serialPort.value || closingSerial) return
  try {
    const res = await getDeviceSnapshot(['serialOpened'])
    const opened = res.data?.serialOpened || []
    const alive = new Set(
      opened.filter(p => p && p.alive !== false).map(p => String(p.port || '').toUpperCase())
    )
    if (!alive.has(String(serialPort.value).toUpperCase())) {
      serialConnected.value = false
      xferDeviceId.value = ''
      ElMessage.warning(`串口已断开（${serialPort.value}）`)
    }
  } catch {
    /* ignore */
  }
}

function loadPrefs() {
  try {
    const raw = localStorage.getItem(prefsKey.value)
    const p = raw ? JSON.parse(raw) : {}
    if (p.serialPort) serialPort.value = p.serialPort
    if (p.filterText) filterText.value = p.filterText
  } catch {
    /* ignore */
  }
}

function savePrefs() {
  try {
    localStorage.setItem(
      prefsKey.value,
      JSON.stringify({
        serialPort: serialPort.value,
        filterText: filterText.value
      })
    )
  } catch {
    /* ignore */
  }
}

watch(filterText, savePrefs)

async function restoreBoardLink() {
  try {
    const res = await getDeviceSnapshot(['serialOpened', 'sessions'])
    const opened = res.data?.serialOpened || []
    const alive = new Map()
    for (const p of opened) {
      if (p?.alive === false) continue
      const port = String(p.port || '').trim()
      if (port) alive.set(port.toUpperCase(), port)
    }
    const sessions = res.data?.sessions || []
    const want = sourceTag.value
    for (const s of sessions) {
      const source = String(s.source || '').trim()
      const param = String(s.srcParam || '')
      if (!param.startsWith('serial:')) continue
      const port = param.slice('serial:'.length)
      if (!alive.has(port.toUpperCase())) continue
      if (source === want) {
        serialPort.value = port
        serialConnected.value = true
        xferDeviceId.value = xferSourceId.value
        savePrefs()
        break
      }
    }
  } catch {
    /* ignore */
  }
}

async function loadOrders() {
  const res = await getXlBoardTelecontrolConfig(boardId.value)
  const data = res.data || {}
  rawOrders.value = data.order || {}
  const pages = data.page || []
  const ids = []
  if (pages.length) {
    for (const pg of pages) {
      for (const id of pg.orderList || []) {
        if (rawOrders.value[id] && !ids.includes(id)) ids.push(id)
      }
    }
  }
  if (!ids.length) ids.push(...Object.keys(rawOrders.value))
  orderIds.value = ids
  initCompValues(rawOrders.value)
  // 默认参数预览组帧，指令参数区不再显示 '-'
  await Promise.all(
    orderIds.value.map(id => {
      const ord = rawOrders.value[id]
      return ord ? previewOrder(ord, { showLoading: false }) : Promise.resolve()
    })
  )
}

async function previewOrder(ord, { showLoading = true } = {}) {
  if (showLoading) previewingId.value = ord.id
  try {
    const res = await assembleXlBoardTelecontrol(boardId.value, {
      orderId: ord.id,
      values: valuesForOrder(ord)
    })
    assembledMap[ord.id] = { hex: res.data?.hex || '', length: res.data?.length || 0 }
    if (showLoading && res.data?.tip) {
      ElMessage.warning(res.data.tip)
    }
  } catch (e) {
    if (showLoading) ElMessage.error(e?.message || '组帧失败')
  } finally {
    if (showLoading) previewingId.value = ''
  }
}

function exportPreviewOrders() {
  const list = orderIds.value.map((id) => {
    const ord = rawOrders.value[id] || {}
    const asm = assembledMap[id] || {}
    const hex = asm.hex || ''
    const len = asm.length || hex.trim().split(/\s+/).filter(Boolean).length
    return {
      id: ord.id || id,
      name: ord.name || '',
      hex,
      len
    }
  })
  const blob = new Blob([JSON.stringify(list, null, 2) + '\n'], {
    type: 'application/json;charset=utf-8'
  })
  saveAs(blob, `${boardId.value}-tc-preview.json`)
  ElMessage.success(`已导出 ${list.length} 条指令`)
}

async function sendOrder(ord) {
  if (!serialConnected.value || !deviceId.value) {
    ElMessage.warning('请先连接串口')
    return
  }
  sendingId.value = ord.id
  try {
    const res = await sendXlBoardTelecontrol(boardId.value, {
      deviceId: deviceId.value,
      orderId: ord.id,
      values: valuesForOrder(ord),
      name: ord.name
    })
    if (res.data?.hex) {
      assembledMap[ord.id] = { hex: res.data.hex, length: res.data.length || 0 }
    }
    if (res.data?.tip) {
      ElMessage.warning(res.data.tip)
    }
    notifyPayloadSendResult(res)
  } catch (e) {
    ElMessage.error(e?.message || '发送失败')
  } finally {
    sendingId.value = ''
  }
}

onMounted(async () => {
  loadPrefs()
  const entry = await getDeviceConnectEntry(boardId.value)
  if (entry) boardConnectCfg.value = { ...FALLBACK_SERIAL, ...entry }
  await prefetchDeviceSnapshot()
  await restoreBoardLink()
  linkTimer = setInterval(checkLinkStatus, 2000)
  try {
    await loadOrders()
  } catch (e) {
    ElMessage.error(e?.message || '加载遥控配置失败')
  }
})

watch(boardId, async id => {
  const entry = await getDeviceConnectEntry(id)
  boardConnectCfg.value = entry ? { ...FALLBACK_SERIAL, ...entry } : { ...FALLBACK_SERIAL }
})

onUnmounted(() => {
  if (linkTimer) clearInterval(linkTimer)
})
</script>

<style scoped>
.xl-board-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-height: 100%;
  min-height: 480px;
  overflow: hidden;
  box-sizing: border-box;
}
.left-toolbar {
  flex-shrink: 0;
  height: 32px;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
}
.left-toolbar :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 10px;
}
.btn-connected {
  --el-button-bg-color: var(--el-color-success-light-9);
  --el-button-border-color: var(--el-color-success);
  --el-button-text-color: var(--el-color-success);
}
.main-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) 2fr;
  gap: 10px;
}
.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.col-left .panel-tc {
  flex: 1.4;
  min-height: 0;
}
.col-left .panel-xfer {
  flex: 0.8;
  min-height: 0;
}
.col-right .panel-tm {
  flex: 1;
  min-height: 0;
  padding: 4px 8px;
  box-sizing: border-box;
}
.panel-tm :deep(.payload-tm-table) {
  height: 100%;
}
.panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--el-border-color);
  font-weight: 600;
  font-size: 13px;
  flex-shrink: 0;
}
.panel-title {
  line-height: 1.2;
}
.export-tc-btn {
  font-size: 12px !important;
  font-weight: 400 !important;
  height: auto !important;
  padding: 0 !important;
  margin: 0 !important;
  line-height: 1.2 !important;
  transform: translateY(1px);
}
.filter-input {
  margin-left: auto;
  width: 200px;
}
.panel-body {
  flex: 1;
  min-height: 0;
}
.order-list {
  padding: 8px;
}
.order-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.order-title {
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 13px;
}
.order-desc-hex :deep(.el-descriptions__content) {
  word-break: break-all;
  font-family: monospace;
  font-size: 12px;
}
.comp-field {
  width: 200px;
}
</style>
