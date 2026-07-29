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
            <span>遥控</span>
            <el-input
              v-model="filterText"
              clearable
              size="small"
              placeholder="搜索指令代号/名称（空格分词）"
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
          <div class="panel-head">
            <span class="tm-head-left">
              遥测 · {{ tmName || tableKey }}
              <span class="tm-key-tag">({{ tableKey }})</span>
            </span>
            <span v-if="tmTs" class="tm-ts">{{ tmTs }}</span>
          </div>
          <div class="panel-body tm-table-wrap">
            <el-table :data="tmRows" size="small" height="100%" border stripe empty-text="暂无数据">
              <el-table-column label="编号" width="88">
                <template #default="{ row }">
                  <el-tooltip
                    v-if="tmDefById[row.id]"
                    placement="right"
                    :show-after="200"
                    effect="light"
                    popper-class="tm-cfg-tooltip"
                  >
                    <template #content>
                      <pre class="tm-cfg-json">{{ cfgJson(row.id) }}</pre>
                    </template>
                    <span class="id-cell">{{ row.id }}</span>
                  </el-tooltip>
                  <span v-else>{{ row.id }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="参数名称" min-width="140" show-overflow-tooltip />
              <el-table-column label="当前值" width="120">
                <template #default="{ row }">{{ row.show ?? row.value }}</template>
              </el-table-column>
              <el-table-column prop="unit" label="单位" width="64" />
              <el-table-column prop="hex" label="HEX" min-width="90" show-overflow-tooltip />
            </el-table>
          </div>
        </div>
      </div>
    </div>

    <SerialConnectDialog
      v-model="serialDlg.visible"
      :source="sourceTag"
      mode="preset"
      :preset="SERIAL_PRESET"
      :baud-choices="[{ value: 115200, label: '115200' }]"
      :preferred-port="serialPort"
      :fallback-parsers="[{ id: 'xl_board_tm', name: 'XL单板遥测' }]"
      :fallback-assemblers="[{ id: 'passthrough', name: '透传（默认）' }]"
      @success="onSerialSuccess"
    />
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { closeSerialPort, getDeviceSnapshot } from '@/api/payload/device'
import {
  getXlBoardTelecontrolConfig,
  getXlBoardTelemetryTable,
  assembleXlBoardTelecontrol,
  sendXlBoardTelecontrol
} from '@/api/payload/xlBoard'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import PayloadTransferInfo from '@/components/Payload/PayloadTransferInfo.vue'
import SerialConnectDialog from '@/components/Payload/SerialConnectDialog.vue'
import { prefetchDeviceSnapshot } from '@/utils/deviceSnapshotCache'

const props = defineProps({
  /** rkdj | zk */
  board: { type: String, required: true },
  /** 页面标题（菜单名） */
  title: { type: String, default: '' }
})

const boardId = computed(() => String(props.board || '').toLowerCase())
const tableKey = computed(() => (boardId.value === 'zk' ? 'ZK' : 'RKDJ'))
const sourceTag = computed(() => boardId.value)
const prefsKey = computed(() => `payload:board:${boardId.value}:prefs`)

const SERIAL_PRESET = {
  baudChoice: 115200,
  baudrate: 115200,
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE',
  assemblerId: 'passthrough',
  parserId: 'xl_board_tm'
}

const serialPort = ref('')
const serialConnected = ref(false)
const filterText = ref('')
const rawOrders = ref({})
const orderIds = ref([])
const compValues = reactive({})
const assembledMap = reactive({})
const sendingId = ref('')
const previewingId = ref('')

const tmName = ref('')
const tmTs = ref('')
const tmRows = ref([])
const tmDataId = ref(null)
const tmCfgRows = ref([])
const tmDefById = ref({})

const xferDeviceId = ref('')

const serialDlg = reactive({ visible: false })

let tmTimer = null
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
  const tokens = String(filterText.value || '')
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
  const list = orderIds.value.map(id => rawOrders.value[id]).filter(Boolean)
  if (!tokens.length) return list
  return list.filter(o => {
    const hay = `${o.id || ''} ${o.name || ''}`.toLowerCase()
    return tokens.every(t => hay.includes(t))
  })
})

function compType(comp) {
  return String(comp?.componentType || 'fixed').toLowerCase()
}

function numBound(v) {
  if (v === '' || v === null || v === undefined) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
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

function initCompValues(orders) {
  for (const [id, ord] of Object.entries(orders || {})) {
    if (!compValues[id]) compValues[id] = {}
    ;(ord.component || []).forEach((comp, idx) => {
      if (compValues[id][idx] === undefined) {
        const def = comp.defaultVal
        if (compType(comp) === 'number') {
          const n = Number(def)
          compValues[id][idx] = Number.isFinite(n) ? n : 0
        } else {
          compValues[id][idx] = def ?? ''
        }
      }
    })
  }
}

function valuesForOrder(ord) {
  return (ord.component || []).map((comp, idx) => {
    if (compType(comp) === 'fixed') return comp.defaultVal
    const v = compValues[ord.id]?.[idx]
    return v === undefined || v === null || v === '' ? comp.defaultVal : v
  })
}

function rowsFromCfg(cfgRows) {
  return (cfgRows || [])
    .filter(r => r?.id)
    .map(r => ({
      id: r.id,
      name: r.name || '',
      value: '',
      show: '',
      unit: r.unit || '',
      hex: ''
    }))
}

function cfgJson(id) {
  const def = tmDefById.value[id]
  return def ? JSON.stringify(def, null, 2) : ''
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
  refreshTm({ needCfg: true })
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
  resetTmToEmptyTable()
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
      resetTmToEmptyTable()
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
        await refreshTm({ needCfg: true })
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
  } catch (e) {
    if (showLoading) ElMessage.error(e?.message || '组帧失败')
  } finally {
    if (showLoading) previewingId.value = ''
  }
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
    notifyPayloadSendResult(res)
  } catch (e) {
    ElMessage.error(e?.message || '发送失败')
  } finally {
    sendingId.value = ''
  }
}

function resetTmToEmptyTable() {
  tmDataId.value = null
  tmTs.value = ''
  tmRows.value = rowsFromCfg(tmCfgRows.value)
}

async function refreshTm({ needCfg = false } = {}) {
  try {
    if (needCfg || !tmCfgRows.value.length) {
      const res = await getXlBoardTelemetryTable(boardId.value, null, true)
      const data = res.data || {}
      tmName.value = data.name || tableKey.value
      const cfg = data.cfg || {}
      tmCfgRows.value = cfg.row || []
      const map = {}
      for (const r of tmCfgRows.value) {
        if (r?.id) map[r.id] = r
      }
      tmDefById.value = map
      if (!serialConnected.value) {
        tmRows.value = rowsFromCfg(tmCfgRows.value)
        return
      }
    }
    if (!serialConnected.value) return
    const res = await getXlBoardTelemetryTable(boardId.value, tmDataId.value, false)
    const data = res.data || {}
    if (data.name) tmName.value = data.name
    if (data.ts) tmTs.value = data.ts
    if (data.dataId != null) tmDataId.value = data.dataId
    const rows = (data.rows || []).filter(r => r?.id)
    tmRows.value = rows.length
      ? rows.map(r => ({
          id: r.id,
          name: r.name || '',
          value: r.value,
          show: r.show,
          unit: r.unit || '',
          hex: r.hex || ''
        }))
      : rowsFromCfg(tmCfgRows.value)
  } catch {
    if (!tmRows.value.length) tmRows.value = rowsFromCfg(tmCfgRows.value)
  }
}

onMounted(async () => {
  loadPrefs()
  // 串口状态优先于遥测/遥控配置
  await prefetchDeviceSnapshot()
  await restoreBoardLink()
  linkTimer = setInterval(checkLinkStatus, 2000)
  ;(async () => {
    try {
      await loadOrders()
    } catch (e) {
      ElMessage.error(e?.message || '加载遥控配置失败')
    }
    try {
      await refreshTm({ needCfg: true })
    } catch {
      /* ignore */
    }
  })()
  tmTimer = setInterval(() => {
    if (serialConnected.value) refreshTm({ needCfg: false })
  }, 1000)
})

onUnmounted(() => {
  if (tmTimer) clearInterval(tmTimer)
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
.filter-input {
  margin-left: auto;
  width: 200px;
}
.tm-ts {
  margin-left: auto;
  font-weight: 400;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tm-head-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.tm-key-tag {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.panel-body {
  flex: 1;
  min-height: 0;
}
.tm-table-wrap {
  padding: 0;
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
.id-cell {
  cursor: help;
}
</style>

<style>
.tm-cfg-tooltip .tm-cfg-json {
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre;
  color: inherit;
  font-family: var(--el-font-family-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.45;
}
</style>
