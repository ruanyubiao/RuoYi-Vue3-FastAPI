<template>
  <div class="app-container xfer-page">
    <div class="xfer-body">
      <div class="xfer-left">
        <el-card shadow="never" class="block-card device-card">
          <el-form label-width="88px" label-position="left" class="xfer-form">
            <el-form-item label="设备列表">
              <div class="device-row">
                <el-select
                  v-model="selectedId"
                  clearable
                  filterable
                  placeholder="请选择设备"
                  class="device-select"
                  @change="onDeviceChange"
                >
                  <el-option-group v-if="onlineDevices.length" label="已连接">
                    <el-option
                      v-for="d in onlineDevices"
                      :key="d.deviceId"
                      :label="d.label"
                      :value="d.deviceId"
                    />
                  </el-option-group>
                  <el-option-group v-if="historyDevices.length" label="历史连接">
                    <el-option
                      v-for="d in historyDevices"
                      :key="d.deviceId"
                      :label="d.label"
                      :value="d.deviceId"
                    />
                  </el-option-group>
                </el-select>
                <el-button type="primary" plain size="small" :loading="refreshing" @click="refreshDevices">
                  刷新设备
                </el-button>
              </div>
              <ul class="hint-list">
                <li>设备请在首页「新建连接」打开。</li>
                <li>本页仅做原始数据发送与接收显示。</li>
                <li>历史设备可查看收发记录。</li>
              </ul>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="block-card send-card">
          <template v-if="!current">
            <div class="empty-tip">请先选择设备</div>
          </template>
          <template v-else-if="!current.alive">
            <div class="empty-tip">当前为历史设备（离线），仅可查看接收记录，不可发送。</div>
          </template>
          <template v-else-if="current.kind === 'can'">
            <el-form label-width="88px" label-position="left" class="xfer-form">
              <el-form-item label="帧ID(HEX)">
                <el-input
                  :model-value="canSend.frameIdHex"
                  placeholder="00000000"
                  class="send-input"
                  @update:model-value="onCanFrameIdInput"
                  @blur="onCanFrameIdBlur"
                />
              </el-form-item>
              <el-form-item label="数据(HEX)">
                <el-input
                  :model-value="canSend.dataHex"
                  placeholder="00 01 02 03 04 05 06 07"
                  class="send-input"
                  @update:model-value="onCanDataHexInput"
                  @blur="onCanDataHexBlur"
                />
              </el-form-item>
              <el-form-item label=" ">
                <el-button type="success" @click="sendCanRaw">发送</el-button>
              </el-form-item>
            </el-form>
          </template>
          <template v-else-if="current.kind === 'serial'">
            <el-form label-width="88px" label-position="left" class="xfer-form">
              <RawDataSendPanel v-model="serialSend" @send="sendSerialRaw" />
            </el-form>
          </template>
          <template v-else-if="current.kind === 'udp'">
            <el-form label-width="88px" label-position="left" class="xfer-form">
              <RawDataSendPanel v-model="udpSend" @send="sendUdpRaw">
                <template #before>
                  <el-form-item label="远程地址">
                    <el-input v-model="udpRemoteHost" placeholder="如 192.168.1.10" class="send-input" />
                  </el-form-item>
                  <el-form-item label="远程端口">
                    <el-input-number
                      v-model="udpRemotePort"
                      :min="1"
                      :max="65535"
                      controls-position="right"
                      class="send-input"
                    />
                  </el-form-item>
                </template>
              </RawDataSendPanel>
            </el-form>
          </template>
        </el-card>
      </div>

      <div class="xfer-right">
        <el-card shadow="never" class="recv-card">
          <IoLogPanel
            v-if="selectedId"
            ref="ioLogRef"
            :device-id="selectedId"
            :log-style="ioLogStyle"
            :hex-only="current?.kind === 'can' || String(selectedId).startsWith('can:')"
          />
          <div v-else class="empty-tip">请先选择设备</div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup name="DebugXfer">
import { ElMessage } from 'element-plus'
import RawDataSendPanel from '@/components/Payload/RawDataSendPanel.vue'
import IoLogPanel from '@/components/Payload/IoLogPanel.vue'
import { listCanChannels, listSerialOpened, listNetOpened } from '@/api/payload/device'
import { sendCanRaw as sendCanRawApi, sendTelecontrol } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import { HEX_INPUT_WARN, isHexText, normalizeHexDisplay } from '@/utils/payloadRawData'

const XFER_DEVICE_KEY = 'payload:xfer:deviceId'
const HISTORY_KEY = 'payload:xfer:deviceHistory'
const SEND_DRAFT_KEY = 'payload:xfer:sendDraftByDevice'
const HISTORY_MAX = 30

const DEFAULT_CAN_SEND = { frameIdHex: '00000000', dataHex: '00 01 02 03 04 05 06 07' }
const DEFAULT_RAW_SEND = { text: '', isHex: false, parseEscape: false, lineEnding: 'none' }

const refreshing = ref(false)
const devices = ref([])
const selectedId = ref(localStorage.getItem(XFER_DEVICE_KEY) || '')
const ioLogRef = ref(null)

const canSend = reactive({ ...DEFAULT_CAN_SEND })
const serialSend = ref({ ...DEFAULT_RAW_SEND })
const udpSend = ref({ ...DEFAULT_RAW_SEND })
const udpRemoteHost = ref('')
const udpRemotePort = ref(9000)

const CAN_FRAMEID_WARN = '帧ID(HEX)只能输入十六进制字符(空格会自动去掉)'
const CAN_FRAMEID_OVERFLOW_WARN = '帧ID溢出。标准帧有效范围0-0x7FF，扩展帧有效范围0-0x1FFFFFF'

const current = computed(() => devices.value.find(d => d.deviceId === selectedId.value) || null)
const onlineDevices = computed(() => devices.value.filter(d => d.alive))
const historyDevices = computed(() => devices.value.filter(d => !d.alive))

/** 不依赖 devices 是否已拉回，避免刷新瞬间 UDP 缺 from */
const ioLogStyle = computed(() => {
  if (current.value?.kind === 'udp') return 'udp'
  if (String(selectedId.value || '').startsWith('udp:')) return 'udp'
  return 'default'
})

function readSendDrafts() {
  try {
    const raw = localStorage.getItem(SEND_DRAFT_KEY)
    const obj = raw ? JSON.parse(raw) : {}
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

function writeSendDrafts(map) {
  try {
    localStorage.setItem(SEND_DRAFT_KEY, JSON.stringify(map))
  } catch {
    /* ignore */
  }
}

function resetSendForms() {
  Object.assign(canSend, DEFAULT_CAN_SEND)
  serialSend.value = { ...DEFAULT_RAW_SEND }
  udpSend.value = { ...DEFAULT_RAW_SEND }
  udpRemoteHost.value = ''
  udpRemotePort.value = 9000
}

/** 切换设备时加载该设备上次发送成功后保存的草稿 */
function loadSendDraft(deviceId, kind) {
  resetSendForms()
  if (!deviceId) return
  const draft = readSendDrafts()[deviceId]
  if (!draft || typeof draft !== 'object') return
  if (kind === 'can' && draft.can) {
    if (draft.can.frameIdHex != null) canSend.frameIdHex = String(draft.can.frameIdHex)
    if (draft.can.dataHex != null) canSend.dataHex = String(draft.can.dataHex)
  } else if (kind === 'serial' && draft.serial) {
    serialSend.value = {
      text: draft.serial.text != null ? String(draft.serial.text) : '',
      isHex: !!draft.serial.isHex,
      parseEscape: !!draft.serial.parseEscape,
      lineEnding: draft.serial.lineEnding || 'none'
    }
  } else if (kind === 'udp' && draft.udp) {
    udpSend.value = {
      text: draft.udp.text != null ? String(draft.udp.text) : '',
      isHex: !!draft.udp.isHex,
      parseEscape: !!draft.udp.parseEscape,
      lineEnding: draft.udp.lineEnding || 'none'
    }
    if (draft.udp.remoteHost != null) udpRemoteHost.value = String(draft.udp.remoteHost)
    if (draft.udp.remotePort != null) {
      const port = Number(draft.udp.remotePort)
      udpRemotePort.value = Number.isFinite(port) && port > 0 ? port : 9000
    }
  }
}

/** 点击发送成功后按设备保存发送区全部控件状态 */
function saveSendDraft(deviceId, kind) {
  if (!deviceId || !kind) return
  const map = readSendDrafts()
  const prev = map[deviceId] && typeof map[deviceId] === 'object' ? map[deviceId] : {}
  if (kind === 'can') {
    map[deviceId] = {
      ...prev,
      kind,
      can: {
        frameIdHex: canSend.frameIdHex,
        dataHex: canSend.dataHex
      },
      ts: Date.now()
    }
  } else if (kind === 'serial') {
    map[deviceId] = {
      ...prev,
      kind,
      serial: { ...serialSend.value },
      ts: Date.now()
    }
  } else if (kind === 'udp') {
    map[deviceId] = {
      ...prev,
      kind,
      udp: {
        ...udpSend.value,
        remoteHost: udpRemoteHost.value,
        remotePort: udpRemotePort.value
      },
      ts: Date.now()
    }
  }
  writeSendDrafts(map)
}

function applySendDraftForSelection(id) {
  const d = devices.value.find(x => x.deviceId === id)
  loadSendDraft(id, d?.kind)
}

function formatBaseLabel(kind, d) {
  if (kind === 'can') {
    const idx = d.devIndex != null ? `卡${d.devIndex}/通道${d.canIndex}` : d.deviceId
    return `CAN ${d.deviceId}（${idx}）`
  }
  if (kind === 'serial') return `串口 ${d.port || d.deviceId}`
  if (kind === 'udp') {
    const host = d.localHost || '?'
    const port = d.localPort != null ? d.localPort : '?'
    return `UDP ${host}:${port}`
  }
  return d.deviceId
}

function withStatus(base, alive) {
  return `${base} · ${alive ? '在线' : '离线'}`
}

function readHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function writeHistory(list) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_MAX)))
  } catch {
    /* ignore */
  }
}

function rememberDevice(entry) {
  if (!entry?.deviceId) return
  const rest = readHistory().filter(h => h.deviceId !== entry.deviceId)
  writeHistory([
    {
      deviceId: entry.deviceId,
      kind: entry.kind,
      baseLabel: entry.baseLabel || formatBaseLabel(entry.kind, entry),
      port: entry.port,
      localHost: entry.localHost,
      localPort: entry.localPort,
      vendor: entry.vendor,
      devIndex: entry.devIndex,
      canIndex: entry.canIndex,
      ts: Date.now()
    },
    ...rest
  ])
}

async function refreshDevices() {
  refreshing.value = true
  try {
    const [canRes, serialRes, netRes] = await Promise.all([
      listCanChannels(),
      listSerialOpened(),
      listNetOpened()
    ])
    const online = []
    for (const d of canRes.data || []) {
      if (d.demo || !d.alive) continue
      const baseLabel = formatBaseLabel('can', d)
      const entry = {
        kind: 'can',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      }
      online.push(entry)
      rememberDevice(entry)
    }
    for (const d of serialRes.data || []) {
      if (!d.alive) continue
      const baseLabel = formatBaseLabel('serial', d)
      const entry = {
        kind: 'serial',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      }
      online.push(entry)
      rememberDevice(entry)
    }
    for (const d of netRes.data || []) {
      if (!d.alive) continue
      const baseLabel = formatBaseLabel('udp', d)
      const entry = {
        kind: 'udp',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      }
      online.push(entry)
      rememberDevice(entry)
    }

    const onlineIds = new Set(online.map(d => d.deviceId))
    const history = readHistory()
      .filter(h => h.deviceId && !onlineIds.has(h.deviceId))
      .map(h => {
        const baseLabel = h.baseLabel || formatBaseLabel(h.kind, h)
        return {
          ...h,
          alive: false,
          baseLabel,
          label: withStatus(baseLabel, false)
        }
      })

    devices.value = [...online, ...history]

    if (selectedId.value && !devices.value.some(d => d.deviceId === selectedId.value)) {
      selectedId.value = ''
      localStorage.removeItem(XFER_DEVICE_KEY)
    }
    if (!selectedId.value && online.length === 1) {
      selectedId.value = online[0].deviceId
      localStorage.setItem(XFER_DEVICE_KEY, selectedId.value)
      rememberDevice(online[0])
    }
    if (selectedId.value) applySendDraftForSelection(selectedId.value)
  } finally {
    refreshing.value = false
  }
}

function onDeviceChange(id) {
  if (id) {
    localStorage.setItem(XFER_DEVICE_KEY, id)
    const d = devices.value.find(x => x.deviceId === id)
    if (d) rememberDevice(d)
    applySendDraftForSelection(id)
  } else {
    localStorage.removeItem(XFER_DEVICE_KEY)
    resetSendForms()
  }
}

function onCanFrameIdInput(next) {
  const noSpace = String(next ?? '').replace(/\s+/g, '')
  if (/[^0-9a-fA-F]/.test(noSpace)) return ElMessage.warning(CAN_FRAMEID_WARN)
  canSend.frameIdHex = noSpace.slice(0, 8).toUpperCase()
}
function onCanFrameIdBlur() {
  const raw = String(canSend.frameIdHex || '').replace(/\s+/g, '')
  if (!raw) return
  if (/[^0-9a-fA-F]/.test(raw) || raw.length > 8) return ElMessage.warning(CAN_FRAMEID_WARN)
  canSend.frameIdHex = raw.toUpperCase().padStart(8, '0')
}
function onCanDataHexInput(next) {
  const raw = String(next ?? '')
  if (!isHexText(raw, { input: true })) return ElMessage.warning(HEX_INPUT_WARN)
  const parts = (normalizeHexDisplay(raw) || '').split(' ').filter(Boolean)
  if (parts.length > 8) return ElMessage.warning('数据(HEX)最多8个字节')
  canSend.dataHex = raw
}
function onCanDataHexBlur() {
  const raw = String(canSend.dataHex || '')
  if (!raw.trim()) return
  if (!isHexText(raw, { input: true })) return ElMessage.warning(HEX_INPUT_WARN)
  const norm = normalizeHexDisplay(raw)
  if ((norm || '').split(' ').filter(Boolean).length > 8) return ElMessage.warning('数据(HEX)最多8个字节')
  canSend.dataHex = norm
}

function ensureOnline() {
  if (!current.value?.alive) {
    ElMessage.warning('设备离线，仅可查看历史接收记录')
    return false
  }
  return true
}

async function sendCanRaw() {
  if (!selectedId.value || !ensureOnline()) return
  const frameIdInput = String(canSend.frameIdHex || '').trim().replace(/\s+/g, '')
  if (!/^[0-9a-fA-F]{1,8}$/.test(frameIdInput)) return ElMessage.warning(CAN_FRAMEID_WARN)
  const frameIdPadded = frameIdInput.toUpperCase().padStart(8, '0')
  canSend.frameIdHex = frameIdPadded
  onCanDataHexBlur()
  const frameIdNum = parseInt(frameIdPadded, 16)
  if (frameIdNum > 0x7FF) return ElMessage.warning(CAN_FRAMEID_OVERFLOW_WARN)
  if (!isHexText(String(canSend.dataHex || ''), { input: true })) return ElMessage.warning(HEX_INPUT_WARN)
  try {
    const res = await sendCanRawApi({
      deviceId: selectedId.value,
      frameIdHex: frameIdPadded,
      dataHex: String(canSend.dataHex || '')
    })
    notifyPayloadSendResult(res, { deviceId: selectedId.value, channel: 'CAN' })
    saveSendDraft(selectedId.value, 'can')
    ioLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function sendSerialRaw(hex) {
  if (!selectedId.value || !ensureOnline()) return
  try {
    const res = await sendTelecontrol({
      deviceId: selectedId.value,
      name: 'SERIAL_RAW',
      hex,
      displayHex: !!serialSend.value.isHex
    })
    notifyPayloadSendResult(res, { deviceId: selectedId.value, channel: '串口' })
    saveSendDraft(selectedId.value, 'serial')
    ioLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function sendUdpRaw(hex) {
  if (!selectedId.value || !ensureOnline()) return
  const host = String(udpRemoteHost.value || '').trim()
  const port = Number(udpRemotePort.value)
  if (!host) return ElMessage.warning('请填写远程地址')
  if (!Number.isFinite(port) || port <= 0 || port > 65535) return ElMessage.warning('请填写有效远程端口')
  try {
    const res = await sendTelecontrol({
      deviceId: selectedId.value,
      name: 'UDP_RAW',
      hex,
      remoteHost: host,
      remotePort: port,
      displayHex: !!udpSend.value.isHex
    })
    notifyPayloadSendResult(res, { deviceId: selectedId.value, channel: 'UDP' })
    saveSendDraft(selectedId.value, 'udp')
    ioLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function pollSelected() {
  // 静默刷新在线状态；离线设备保留在历史列表中供查看
  try {
    await refreshDevicesQuiet()
  } catch {
    /* ignore */
  }
}

async function refreshDevicesQuiet() {
  const prev = refreshing.value
  refreshing.value = false
  try {
    const [canRes, serialRes, netRes] = await Promise.all([
      listCanChannels(),
      listSerialOpened(),
      listNetOpened()
    ])
    const online = []
    for (const d of canRes.data || []) {
      if (d.demo || !d.alive) continue
      const baseLabel = formatBaseLabel('can', d)
      online.push({
        kind: 'can',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      })
    }
    for (const d of serialRes.data || []) {
      if (!d.alive) continue
      const baseLabel = formatBaseLabel('serial', d)
      online.push({
        kind: 'serial',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      })
    }
    for (const d of netRes.data || []) {
      if (!d.alive) continue
      const baseLabel = formatBaseLabel('udp', d)
      online.push({
        kind: 'udp',
        deviceId: d.deviceId,
        alive: true,
        baseLabel,
        label: withStatus(baseLabel, true),
        ...d
      })
    }
    for (const e of online) rememberDevice(e)
    const onlineIds = new Set(online.map(d => d.deviceId))
    const history = readHistory()
      .filter(h => h.deviceId && !onlineIds.has(h.deviceId))
      .map(h => {
        const baseLabel = h.baseLabel || formatBaseLabel(h.kind, h)
        return { ...h, alive: false, baseLabel, label: withStatus(baseLabel, false) }
      })
    devices.value = [...online, ...history]
  } finally {
    refreshing.value = prev
  }
}

let timer = null
onMounted(async () => {
  await refreshDevices()
  if (selectedId.value) applySendDraftForSelection(selectedId.value)
  timer = setInterval(pollSelected, 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.xfer-page {
  height: calc(100vh - var(--app-main-offset, 84px) - var(--app-footer-offset, 0px));
  box-sizing: border-box;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding-bottom: 12px;
}
.xfer-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.xfer-left {
  width: 42%;
  max-width: 560px;
  min-width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}
.xfer-right {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.block-card {
  margin-bottom: 0;
}
.device-card {
  flex-shrink: 0;
}
.device-card :deep(.el-card__body) {
  padding-top: 14px;
}
.send-card {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.send-card :deep(.el-card__body) {
  padding-top: 14px;
}
.xfer-form {
  max-width: 100%;
}
.xfer-form :deep(.el-form-item__label) {
  justify-content: flex-start;
  padding-right: 8px;
}
.xfer-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.device-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  width: 100%;
}
.device-select {
  width: 280px;
  max-width: 100%;
}
.send-input {
  width: 100%;
  max-width: 280px;
}
.xfer-form :deep(.send-input) {
  width: 280px;
  max-width: 100%;
}
.xfer-form :deep(.el-input-number.send-input) {
  width: 280px;
  max-width: 100%;
}
.xfer-form :deep(.el-input-number.send-input .el-input__inner),
.xfer-form :deep(.el-input-number.send-input input) {
  text-align: left;
}
.hint-list {
  margin: 10px 0 0;
  padding-left: 1.25em;
  list-style: disc;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}
.hint-list li {
  padding-left: 2px;
}
.empty-tip {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  padding: 8px 0;
}
.recv-card {
  flex: 1;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  margin-bottom: 0;
}
.recv-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding-top: 14px;
}
</style>
