<template>
  <div class="app-container control-page">
    <el-card shadow="never">
      <template #header><span>设备连接</span></template>

      <el-row :gutter="12" class="device-row">
        <el-col :span="12" class="device-col">
          <el-card shadow="never" class="device-card">
            <template #header><span>CAN连接</span></template>
            <el-form label-width="100px" class="control-form">
              <el-form-item label="厂商">
                <div class="port-row">
                  <el-select
                    :key="canVendorSelectKey"
                    v-model="canForm.vendor"
                    :disabled="canConnected || canRefreshing"
                    placeholder="请选择厂商"
                    style="width: 220px"
                  >
                    <el-option
                      v-for="v in canVendors"
                      :key="`${v.value}-${v.name}`"
                      :label="formatCanVendorLabel(v)"
                      :value="v.value"
                    />
                  </el-select>
                  <el-button
                    type="primary"
                    plain
                    icon="Refresh"
                    :loading="canRefreshing"
                    :disabled="canConnected"
                    @click="() => refreshCanVendors(true)"
                  >刷新</el-button>
                </div>
              </el-form-item>
              <el-form-item label="设备索引号">
                <el-select v-model="canForm.devIndex" :disabled="canConnected" style="width: 220px">
                  <el-option :label="'0'" :value="0" />
                </el-select>
              </el-form-item>
              <el-form-item label="通道号">
                <el-select v-model="canForm.canIndex" :disabled="canConnected" style="width: 220px">
                  <el-option v-for="ch in canIndexOptions" :key="ch.value" :label="ch.label" :value="ch.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="波特率">
                <el-select v-model="canForm.baudRate" :disabled="canConnected" style="width: 220px">
                  <el-option v-for="b in baudOptions" :key="b.value" :label="b.label" :value="b.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="线缆">
                <el-select v-model="canForm.cableFlag" :disabled="canConnected" style="width: 220px">
                  <el-option v-for="c in cableOptions" :key="c.value" :label="c.label" :value="c.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="目标地址">
                <el-select v-model="canForm.nodeAddrTo" :disabled="canConnected" style="width: 220px">
                  <el-option v-for="n in nodeAddrOptions" :key="n.value" :label="n.label" :value="n.value" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="handleOpenCan" :disabled="canConnected || canForm.vendor == null">打开</el-button>
                <el-button @click="handleCloseCan" :disabled="!canConnected">关闭</el-button>
                <el-tag :type="canConnected ? 'success' : 'info'" style="margin-left: 12px">
                  {{ canConnected ? '已连接' : '未连接' }} {{ activeDeviceId || '-' }}
                </el-tag>
              </el-form-item>

              <el-divider />
              <div class="send-section">
                <div class="send-title">CAN发送</div>
                <el-form-item label="帧ID(HEX)">
                  <el-input
                    :model-value="canSend.frameIdHex"
                    :disabled="!canConnected"
                    placeholder="00000000"
                    class="send-input"
                    @update:model-value="onCanFrameIdInput"
                    @blur="onCanFrameIdBlur"
                  />
                </el-form-item>
                <el-form-item label="数据(HEX)">
                  <el-input
                    :model-value="canSend.dataHex"
                    :disabled="!canConnected"
                    placeholder="00 01 02 03 04 05 06 07"
                    class="send-input"
                    @update:model-value="onCanDataHexInput"
                    @blur="onCanDataHexBlur"
                  />
                </el-form-item>
                <el-form-item label=" ">
                  <el-button type="success" :disabled="!canConnected" @click="sendCanRaw">发送</el-button>
                </el-form-item>
              </div>
            </el-form>
          </el-card>
        </el-col>

        <el-col :span="12" class="device-col">
          <el-card shadow="never" class="device-card">
            <template #header><span>串口连接</span></template>
            <el-form label-width="100px" class="control-form">
              <el-form-item label="串口号">
                <div class="port-row">
                  <el-select v-model="serialForm.port" filterable :disabled="serialConnected" style="width: 220px">
                    <el-option v-for="p in serialPorts" :key="p.port" :label="formatPortLabel(p)" :value="p.port" />
                  </el-select>
                  <el-button
                    type="primary"
                    plain
                    icon="Refresh"
                    :loading="serialRefreshing"
                    :disabled="serialConnected"
                    @click="refreshSerialPorts"
                  >刷新</el-button>
                </div>
              </el-form-item>
              <el-form-item label="波特率">
                <el-select v-model="serialForm.baudChoice" :disabled="serialConnected" style="width: 220px">
                  <el-option v-for="b in serialBaudChoices" :key="b.value" :label="b.label" :value="b.value" />
                </el-select>
                <el-input-number
                  v-if="serialForm.baudChoice === 'custom'"
                  v-model="serialForm.baudrate"
                  :disabled="serialConnected"
                  :min="110"
                  :step="100"
                  style="width: 180px; margin-left: 8px"
                />
              </el-form-item>
              <el-form-item label="数据位">
                <el-select v-model="serialForm.dataBits" :disabled="serialConnected" style="width: 220px">
                  <el-option v-for="d in dataBitsOptions" :key="d" :label="String(d)" :value="d" />
                </el-select>
              </el-form-item>
              <el-form-item label="停止位">
                <el-select v-model="serialForm.stopBits" :disabled="serialConnected" style="width: 220px">
                  <el-option v-for="s in stopBitsOptions" :key="s" :label="String(s)" :value="s" />
                </el-select>
              </el-form-item>
              <el-form-item label="校验位">
                <el-select v-model="serialForm.parity" :disabled="serialConnected" style="width: 220px">
                  <el-option v-for="p in parityOptions" :key="p.value" :label="p.label" :value="p.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="流控制">
                <el-select v-model="serialForm.flowControl" :disabled="serialConnected" style="width: 220px">
                  <el-option v-for="f in flowOptions" :key="f.value" :label="f.label" :value="f.value" />
                </el-select>
              </el-form-item>

              <el-form-item>
                <el-button type="primary" @click="handleOpenSerial" :disabled="serialConnected">打开</el-button>
                <el-button @click="handleCloseSerial" :disabled="!serialConnected">关闭</el-button>
                <el-tag :type="serialConnected ? 'success' : 'info'" style="margin-left: 12px">
                  {{ serialConnected ? '已连接' : '未连接' }} {{ serialDeviceId || '-' }}
                </el-tag>
              </el-form-item>

              <el-divider />
              <div class="send-section">
                <div class="send-title">串口发送</div>
                <el-form-item label="数据">
                  <el-input
                    :model-value="serialSend.text"
                    :disabled="!serialConnected"
                    placeholder="输入数据"
                    class="send-input"
                    @update:model-value="onSerialSendTextInput"
                    @blur="onSerialSendTextBlur"
                  />
                </el-form-item>
                <el-form-item class="hex-form-item">
                  <div class="hex-inline">
                    <el-checkbox
                      v-model="serialSend.isHex"
                      :disabled="!serialConnected"
                      class="hex-checkbox"
                      @change="handleSerialHexChange"
                    >HEX</el-checkbox>
                    <el-checkbox
                      v-model="serialSend.parseEscape"
                      :disabled="!serialConnected || serialSend.isHex"
                      class="hex-checkbox"
                    >解析转义符</el-checkbox>
                    <el-select
                      v-model="serialSend.lineEnding"
                      :disabled="!serialConnected"
                      class="line-ending-select"
                    >
                      <el-option label="无追加" value="none" />
                      <el-option label="\n" value="lf" />
                      <el-option label="\r" value="cr" />
                      <el-option label="\r\n" value="crlf" />
                    </el-select>
                  </div>
                </el-form-item>
                <el-form-item label=" ">
                    <el-button type="success" :disabled="!serialConnected" @click="sendSerialRaw">发送</el-button>
                </el-form-item>
              </div>
            </el-form>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>定时遥测</span></template>
      <el-form label-width="140px">
        <el-form-item label="定时遥测">
          <el-button type="success" @click="op('timedYc.enable', { enable: true })">打开</el-button>
          <el-button type="danger" @click="op('timedYc.enable', { enable: false })">关闭</el-button>
        </el-form-item>
        <el-form-item label="遥测类型">
          <el-select v-model="timedYc.dataCode" style="width: 120px; margin-right: 8px">
            <el-option v-for="t in tmTypes" :key="t" :label="t" :value="t" />
          </el-select>
          <span style="margin-right: 8px">间隔(ms)</span>
          <el-input-number v-model="timedYc.intervalMs" :min="100" :step="100" style="width: 140px; margin-right: 8px" />
          <el-button @click="op('timedYc.param', timedYc)">设置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>原子钟校时 / 通信速率</span></template>
      <el-form label-width="140px">
        <el-form-item label="原子钟校时">
          <el-button type="success" @click="op('ppsTime.enable', { enable: true })">打开</el-button>
          <el-button type="danger" @click="op('ppsTime.enable', { enable: false })">关闭</el-button>
        </el-form-item>
        <el-form-item label="通信速率统计">
          <el-input-number v-model="rateDuration" :min="60" style="width: 140px; margin-right: 8px" />
          <span style="margin-right: 8px">秒</span>
          <el-button type="primary" @click="op('rate.start', { durationSec: rateDuration })">开始统计</el-button>
          <el-button @click="op('rate.stop')">停止统计</el-button>
        </el-form-item>
        <el-form-item label="统计信息">
          <span>统计时间 {{ rateInfo.time }} | 空口速率 {{ rateInfo.speed }} Mbps | 误码率 {{ rateInfo.err }}</span>
        </el-form-item>
        <el-form-item label="时间补偿(ms)">
          <el-input-number v-model="ppsOffset" style="width: 140px; margin-right: 8px" />
          <el-button @click="op('ppsTime.offset', { offsetMs: ppsOffset })">设置</el-button>
        </el-form-item>
        <el-form-item label="时间同步起始(UTC)">
          <el-date-picker v-model="ppsUtc" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="margin-right: 8px" />
          <el-button @click="op('ppsTime.start', { utc: ppsUtc })">设置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup name="Control">
import { ElMessage } from 'element-plus'
import { openCanChannel, closeCanChannel, listCanVendors, listCanChannels, listSerialPorts, listSerialOpened, openSerialPort, closeSerialPort, getDeviceStatus } from '@/api/payload/device'
import { sendCanRaw as sendCanRawApi, telecontrolControlOp, sendTelecontrol } from '@/api/payload/telecontrol'
import { getTelemetryTable } from '@/api/payload/telemetry'

const ACTIVE_KEY = 'payload:activeDeviceId'
const SERIAL_ACTIVE_KEY = 'payload:serialDeviceId'
const canVendors = ref([])
const canRefreshing = ref(false)
const canVendorSelectKey = ref(0)
const canIndexOptions = [{ value: 0, label: '0' }, { value: 1, label: '1' }]
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
  { value: 0x0D, label: '0x0D = 激光终端A' },
  { value: 0x0E, label: '0x0E = 激光终端B' }
]
const canForm = reactive({ vendor: null, devIndex: 0, canIndex: 0, baudRate: 500, nodeAddrTo: 0x0D, cableFlag: 0 })
const canSend = reactive({ frameIdHex: '00000000', dataHex: '00 01 02 03 04 05 06 07' })
const activeDeviceId = ref(localStorage.getItem(ACTIVE_KEY) || '')
const canConnected = ref(false)
const serialRefreshing = ref(false)
const serialPorts = ref([])
const serialConnected = ref(false)
const serialDeviceId = ref(localStorage.getItem(SERIAL_ACTIVE_KEY) || '')
const serialBaudChoices = [
  { value: 110, label: '110' },
  { value: 300, label: '300' },
  { value: 600, label: '600' },
  { value: 1200, label: '1200' },
  { value: 2400, label: '2400' },
  { value: 4800, label: '4800' },
  { value: 9600, label: '9600' },
  { value: 14400, label: '14400' },
  { value: 19200, label: '19200' },
  { value: 38400, label: '38400' },
  { value: 56000, label: '56000' },
  { value: 57600, label: '57600' },
  { value: 115200, label: '115200' },
  { value: 128000, label: '128000' },
  { value: 230400, label: '230400' },
  { value: 256000, label: '256000' },
  { value: 460800, label: '460800' },
  { value: 921600, label: '921600' },
  { value: 1000000, label: '1000000' },
  { value: 2000000, label: '2000000' },
  { value: 'custom', label: 'Customize' }
]
const dataBitsOptions = [5, 6, 7, 8]
const stopBitsOptions = [1, 1.5, 2]
const parityOptions = [
  { value: 'N', label: 'NONE' },
  { value: 'E', label: 'EVEN' },
  { value: 'O', label: 'ODD' },
  { value: 'M', label: 'MARK' },
  { value: 'S', label: 'SPACE' }
]
const flowOptions = [
  { value: 'NONE', label: 'NONE' },
  { value: 'XON/XOFF', label: 'XON/XOFF' },
  { value: 'RTS/CTS', label: 'RTS/CTS' },
  { value: 'DTR/DSR', label: 'DTR/DSR' },
  { value: 'RTS/CTS/XON/XOFF', label: 'RTS/CTS/XON/XOFF' },
  { value: 'DTR/DSR/XON/XOFF', label: 'DTR/DSR/XON/XOFF' }
]
const serialForm = reactive({
  port: '',
  baudChoice: 9600,
  baudrate: 9600,
  dataBits: 8,
  stopBits: 1,
  parity: 'N',
  flowControl: 'NONE'
})
const serialSend = reactive({ text: '', isHex: false, parseEscape: false, lineEnding: 'none' })
const HEX_INPUT_WARN = '当前在十六进制输入模式下，只能输入十六进制形式的字符。'
const CAN_FRAMEID_WARN = '帧ID(HEX)只能输入十六进制字符(空格会自动去掉)'
const CAN_FRAMEID_OVERFLOW_WARN = '帧ID溢出。标准帧有效范围0-0x7FF，扩展帧有效范围0-0x1FFFFFF'
const timedYc = reactive({ dataCode: 'F9', intervalMs: 1000 })
const tmTypes = ['F9', 'F7', 'FF', 'FD', 'FB']
const rateDuration = ref(600)
const rateInfo = reactive({ time: '00:00:00', speed: '0', err: '0' })
const ppsOffset = ref(0)
const ppsUtc = ref('')
let statusTimer = null

function formatPortLabel(p) {
  return p.description ? `${p.port} (${p.description})` : p.port
}

function formatCanVendorLabel(v) {
  return `${v.value} - ${v.name || ''}`
}

function mapCanVendors(raw) {
  return (raw || []).map(v => ({
    value: v.value,
    key: v.key,
    name: v.name
  }))
}

function isPcieVendor(v) {
  const text = `${v.key || ''} ${v.name || ''}`.toUpperCase()
  return text.includes('PCIE')
}

function pickDefaultVendor(vendors) {
  if (!vendors.length) return null
  const pcie = vendors.find(isPcieVendor)
  return pcie ? pcie.value : vendors[0].value
}

async function refreshCanVendors(showMsg = false) {
  if (canRefreshing.value) return
  canRefreshing.value = true
  const prevVendor = canForm.vendor
  try {
    const res = await listCanVendors()
    const data = res.data || {}
    const nextVendors = mapCanVendors(data.vendors)
    canVendors.value = nextVendors
    canVendorSelectKey.value += 1
    if (!canConnected.value) {
      const exists = prevVendor != null && nextVendors.some(v => v.value === prevVendor)
      canForm.vendor = exists ? prevVendor : pickDefaultVendor(nextVendors)
    }
    if (showMsg) ElMessage.success(`已刷新，发现 ${nextVendors.length} 个厂商`)
  } catch (e) {
    canVendors.value = []
    canVendorSelectKey.value += 1
    if (!canConnected.value) canForm.vendor = null
    if (showMsg) ElMessage.error('刷新厂商列表失败')
  } finally {
    canRefreshing.value = false
  }
}

async function refreshSerialPorts(showMsg = true) {
  if (serialRefreshing.value) return
  serialRefreshing.value = true
  const prevPort = serialForm.port
  try {
    const res = await listSerialPorts()
    serialPorts.value = res.data || []
    if (serialPorts.value.length) {
      const exists = serialPorts.value.some(p => p.port === prevPort)
      serialForm.port = exists ? prevPort : serialPorts.value[0].port
    } else {
      serialForm.port = ''
    }
    if (showMsg) ElMessage.success(`已刷新，发现 ${serialPorts.value.length} 个串口`)
  } catch (e) {
    if (showMsg) ElMessage.error('刷新串口列表失败')
  } finally {
    serialRefreshing.value = false
  }
}

async function handleOpenCan() {
  if (canForm.vendor == null) return
  const res = await openCanChannel({ ...canForm })
  activeDeviceId.value = res.data.deviceId
  localStorage.setItem(ACTIVE_KEY, activeDeviceId.value)
  canConnected.value = true
  ElMessage.success('CAN 通道已打开')
}

async function handleCloseCan() {
  await closeCanChannel({ ...canForm })
  canConnected.value = false
  activeDeviceId.value = ''
  localStorage.removeItem(ACTIVE_KEY)
  ElMessage.success('CAN 通道已关闭')
}

async function handleOpenSerial() {
  if (!serialForm.port) return
  if (serialForm.baudChoice !== 'custom') serialForm.baudrate = Number(serialForm.baudChoice)
  const res = await openSerialPort({
    port: serialForm.port,
    baudrate: serialForm.baudrate,
    mode: 'raw',
    dataBits: serialForm.dataBits,
    stopBits: serialForm.stopBits,
    parity: serialForm.parity,
    flowControl: serialForm.flowControl
  })
  serialDeviceId.value = res.data.deviceId
  localStorage.setItem(SERIAL_ACTIVE_KEY, serialDeviceId.value)
  serialConnected.value = true
  ElMessage.success('串口已打开')
}

async function handleCloseSerial() {
  if (!serialForm.port) return
  await closeSerialPort(serialForm.port)
  serialConnected.value = false
  serialDeviceId.value = ''
  localStorage.removeItem(SERIAL_ACTIVE_KEY)
  ElMessage.success('串口已关闭')
}

function cleanHex(text) {
  return (text || '').replace(/[^0-9a-fA-F]/g, '')
}

function _padOddHex(cleaned) {
  if (!cleaned) return ''
  if (cleaned.length % 2 === 0) return cleaned
  // 末尾只有 1 个字符时，自动补 0 变成 2 个：AABBC -> AABB0C
  return cleaned.slice(0, -1) + '0' + cleaned.slice(-1)
}

function _hexTokens(text) {
  if (!text) return []
  return String(text).trim().split(/\s+/).filter(Boolean)
}

function _normalizeHexPairsFromTokens(tokens) {
  const pairs = []
  for (const t of tokens) {
    if (!/^[0-9a-fA-F]+$/.test(t)) return null
    const padded = _padOddHex(t)
    const segs = padded.match(/.{1,2}/g) || []
    for (const s of segs) pairs.push(s.toUpperCase())
  }
  return pairs
}

function isHexText(text, { input = false } = {}) {
  if (!text || !text.trim()) return true
  if (!/^[0-9a-fA-F\s]+$/.test(text)) return false
  if (input) {
    // 输入过程中：仅限制字符集（允许连续输入，如 AA -> AAB），空格随意
    // 最终规范化/发送时会按字节分组，且末尾 1 个字符会自动补 0
    return true
  }
  // 空白字符作为 16 进制分割：a b c -> 0A 0B 0C，ab c -> AB 0C
  const normalized = normalizeHexDisplay(text)
  return /^([0-9a-fA-F]{2})(\s*[0-9a-fA-F]{2})*$/.test(normalized)
}

function onSerialSendTextInput(next) {
  if (serialSend.isHex) {
    if (!isHexText(next, { input: true })) {
      ElMessage.warning(HEX_INPUT_WARN)
      return
    }
  }
  serialSend.text = next
}

function onSerialSendTextBlur() {
  if (!serialSend.isHex) return
  const raw = String(serialSend.text || '')
  if (!raw.trim()) return
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  if (norm) serialSend.text = norm
}

function onCanFrameIdInput(next) {
  const raw = String(next ?? '')
  const noSpace = raw.replace(/\s+/g, '')
  if (/[^0-9a-fA-F]/.test(noSpace)) {
    ElMessage.warning(CAN_FRAMEID_WARN)
    return
  }
  canSend.frameIdHex = noSpace.slice(0, 8).toUpperCase()
}

function onCanFrameIdBlur() {
  const raw = String(canSend.frameIdHex || '').replace(/\s+/g, '')
  if (!raw) return
  if (/[^0-9a-fA-F]/.test(raw) || raw.length > 8) {
    ElMessage.warning(CAN_FRAMEID_WARN)
    return
  }
  canSend.frameIdHex = raw.toUpperCase().padStart(8, '0')
}

function onCanDataHexInput(next) {
  const raw = String(next ?? '')
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  const parts = norm ? norm.split(' ').filter(Boolean) : []
  if (parts.length > 8) {
    ElMessage.warning('数据(HEX)最多8个字节')
    return
  }
  canSend.dataHex = raw
}

function onCanDataHexBlur() {
  const raw = String(canSend.dataHex || '')
  if (!raw.trim()) return
  if (!isHexText(raw, { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  const norm = normalizeHexDisplay(raw)
  const parts = norm ? norm.split(' ').filter(Boolean) : []
  if (parts.length > 8) {
    ElMessage.warning('数据(HEX)最多8个字节')
    return
  }
  canSend.dataHex = norm
}

function parseEscapeSequences(text) {
  let out = ''
  let i = 0
  while (i < text.length) {
    if (text[i] === '\\' && i + 1 < text.length) {
      const next = text[i + 1]
      if (next === 'r') {
        out += '\r'
        i += 2
        continue
      }
      if (next === 'n') {
        out += '\n'
        i += 2
        continue
      }
      if (next === 't') {
        out += '\t'
        i += 2
        continue
      }
      if (next === '\\') {
        out += '\\'
        i += 2
        continue
      }
      if (next === '0') {
        out += '\0'
        i += 2
        continue
      }
      if ((next === 'x' || next === 'X') && i + 3 < text.length) {
        const hex = text.slice(i + 2, i + 4)
        if (/^[0-9a-fA-F]{2}$/.test(hex)) {
          out += String.fromCharCode(parseInt(hex, 16))
          i += 4
          continue
        }
      }
    }
    out += text[i]
    i += 1
  }
  return out
}

function normalizeHexDisplay(text) {
  const tokens = _hexTokens(text)
  if (!tokens.length) return ''
  const pairs = _normalizeHexPairsFromTokens(tokens)
  if (!pairs) return ''
  return pairs.join(' ')
}

function hexToText(hexText) {
  const tokens = _hexTokens(hexText)
  if (!tokens.length) return { ok: true, text: '' }
  const pairs = _normalizeHexPairsFromTokens(tokens)
  if (!pairs) return { ok: false }
  let text = ''
  for (const p of pairs) {
    const byte = parseInt(p, 16)
    if (byte < 32 || byte > 126) return { ok: false }
    text += String.fromCharCode(byte)
  }
  return { ok: true, text }
}

function handleSerialHexChange(checked) {
  if (checked) {
    if (serialSend.text.trim()) {
      // 只要当前内容形态上是十六进制字符（允许末尾 1 个字符），就按 HEX 处理并规范化（自动补 0）
      const looksHex = isHexText(serialSend.text, { input: true })
      serialSend.text = looksHex ? normalizeHexDisplay(serialSend.text) : textToHex(serialSend.text)
    }
    return
  }
  const savedHex = serialSend.text
  const result = hexToText(savedHex)
  if (!result.ok) {
    ElMessage.warning('包含非打印字符，无法转换!')
    serialSend.text = savedHex
    serialSend.isHex = false
    return
  }
  serialSend.text = result.text
}

function toggleHexCheckbox() {
  if (!serialConnected.value) return
  serialSend.isHex = !serialSend.isHex
}

function bytesToHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(' ').toUpperCase()
}

function textToHex(text) {
  const enc = new TextEncoder()
  return bytesToHex(enc.encode(text || ''))
}

const SERIAL_LINE_ENDING_SUFFIX = {
  lf: '\n',
  cr: '\r',
  crlf: '\r\n'
}

function hasSerialLineEnding() {
  return serialSend.lineEnding !== 'none'
}

function getSerialLineEndingSuffix() {
  if (!hasSerialLineEnding()) return ''
  return SERIAL_LINE_ENDING_SUFFIX[serialSend.lineEnding] || ''
}

function appendLineEndingToHex(hex) {
  const suffix = getSerialLineEndingSuffix()
  if (!suffix) return hex
  const suffixHex = textToHex(suffix)
  if (!hex) return suffixHex
  return `${hex} ${suffixHex}`
}

function buildSerialSendHex() {
  if (serialSend.isHex) {
    if (!isHexText(serialSend.text)) return { ok: false, warn: HEX_INPUT_WARN }
    const bodyHex = normalizeHexDisplay(serialSend.text)
    if (!cleanHex(serialSend.text) && !hasSerialLineEnding()) {
      return { ok: false, warn: '请输入数据' }
    }
    return { ok: true, hex: appendLineEndingToHex(bodyHex) }
  }
  let text = serialSend.text
  if (serialSend.parseEscape) {
    text = parseEscapeSequences(text)
  }
  const suffix = getSerialLineEndingSuffix()
  if (suffix) {
    text += suffix
  }
  if (!text) {
    return { ok: false, warn: '请输入数据' }
  }
  return { ok: true, hex: textToHex(text) }
}

async function sendCanRaw() {
  if (!activeDeviceId.value) return
  const frameIdInput = String(canSend.frameIdHex || '').trim().replace(/\s+/g, '')
  if (!/^[0-9a-fA-F]{1,8}$/.test(frameIdInput)) {
    ElMessage.warning('帧ID(HEX)只能输入十六进制字符(空格会自动去掉)')
    return
  }
  const frameIdPadded = frameIdInput.toUpperCase().padStart(8, '0')
  // 点击发送后回填补齐结果（例如 7FF -> 000007FF）
  canSend.frameIdHex = frameIdPadded
  // 点击发送后，回填数据为规范化显示（例如：11 23 4 -> 11 23 04）
  onCanDataHexBlur()
  const frameIdNum = parseInt(frameIdPadded, 16)
  if (frameIdNum > 0x1FFFFFF) {
    ElMessage.warning(CAN_FRAMEID_OVERFLOW_WARN)
    return
  }
  // 当前原始发送走 gpcan SDK 的标准帧(ID 11bit)，超出将被截断成低11位
  if (frameIdNum > 0x7FF) {
    ElMessage.warning(CAN_FRAMEID_OVERFLOW_WARN)
    return
  }
  if (!isHexText(String(canSend.dataHex || ''), { input: true })) {
    ElMessage.warning(HEX_INPUT_WARN)
    return
  }
  await sendCanRawApi({
    deviceId: activeDeviceId.value,
    frameIdHex: frameIdPadded,
    dataHex: String(canSend.dataHex || '')
  })
  ElMessage.success('已发送')
}

async function sendSerialRaw() {
  if (!serialDeviceId.value) return
  const built = buildSerialSendHex()
  if (!built.ok) {
    ElMessage.warning(built.warn)
    return
  }
  if (!built.hex) {
    ElMessage.warning('请输入数据')
    return
  }
  await sendTelecontrol({ deviceId: serialDeviceId.value, name: 'SERIAL_RAW', hex: built.hex })
  ElMessage.success('已发送')
}

async function op(name, params = {}) {
  if (!activeDeviceId.value) {
    ElMessage.warning('请先打开 CAN 通道')
    return
  }
  await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
  ElMessage.success('操作已下发')
}

function applySerialOpened(s) {
  serialDeviceId.value = s.deviceId
  localStorage.setItem(SERIAL_ACTIVE_KEY, s.deviceId)
  serialForm.port = s.port
  if (s.baudrate != null) {
    const baud = Number(s.baudrate)
    const known = serialBaudChoices.some(b => b.value === baud)
    serialForm.baudChoice = known ? baud : 'custom'
    serialForm.baudrate = baud
  }
  if (s.dataBits != null) serialForm.dataBits = Number(s.dataBits)
  if (s.stopBits != null) serialForm.stopBits = Number(s.stopBits)
  if (s.parity) serialForm.parity = s.parity
  if (s.flowControl) serialForm.flowControl = s.flowControl
  serialConnected.value = true
}

async function restoreConnectionState() {
  try {
    const canRes = await listCanChannels()
    const aliveCan = (canRes.data || []).filter(c => c.alive && !c.demo)
    if (aliveCan.length) {
      const ch = aliveCan.find(c => c.deviceId === activeDeviceId.value) || aliveCan[0]
      activeDeviceId.value = ch.deviceId
      localStorage.setItem(ACTIVE_KEY, ch.deviceId)
      canForm.vendor = ch.vendor
      canForm.devIndex = ch.devIndex
      canForm.canIndex = ch.canIndex
      canConnected.value = true
    } else if (activeDeviceId.value) {
      const st = await getDeviceStatus(activeDeviceId.value)
      canConnected.value = !!st.data?.connected
      if (!canConnected.value) {
        activeDeviceId.value = ''
        localStorage.removeItem(ACTIVE_KEY)
      }
    }

    const serialRes = await listSerialOpened()
    const aliveSerial = (serialRes.data || []).filter(s => s.alive)
    if (aliveSerial.length) {
      const s = aliveSerial.find(x => x.deviceId === serialDeviceId.value) || aliveSerial[0]
      applySerialOpened(s)
    } else if (serialDeviceId.value) {
      const st = await getDeviceStatus(serialDeviceId.value)
      serialConnected.value = !!st.data?.connected
      if (!serialConnected.value) {
        serialDeviceId.value = ''
        localStorage.removeItem(SERIAL_ACTIVE_KEY)
      }
    }
  } catch (e) { /* ignore */ }
}

async function pollStatus() {
  try {
    if (activeDeviceId.value) {
      const st = await getDeviceStatus(activeDeviceId.value)
      canConnected.value = !!st.data?.connected
      if (!canConnected.value) {
        activeDeviceId.value = ''
        localStorage.removeItem(ACTIVE_KEY)
        return
      }
      const tm = await getTelemetryTable(activeDeviceId.value, 'FF')
      const rows = tm.data?.rows || []
      const find = (id) => rows.find(r => r.id === id)?.show || '0'
      rateInfo.time = find('JGB132')
      rateInfo.speed = find('JGB133')
      rateInfo.err = find('JGB135')
    }
    if (serialDeviceId.value) {
      const st = await getDeviceStatus(serialDeviceId.value)
      serialConnected.value = !!st.data?.connected
      if (!serialConnected.value) {
        serialDeviceId.value = ''
        localStorage.removeItem(SERIAL_ACTIVE_KEY)
      }
    }
  } catch (e) { /* ignore */ }
}

onMounted(async () => {
  await refreshCanVendors(false)
  await restoreConnectionState()
  refreshSerialPorts(false)
  pollStatus()
  statusTimer = setInterval(pollStatus, 2000)
})
onUnmounted(() => clearInterval(statusTimer))
</script>

<style scoped>
.device-row {
  display: flex;
  align-items: stretch;
}
.device-col {
  display: flex;
}
.device-card {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
}
.device-card :deep(.el-card__body) {
  flex: 1;
}
.control-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.send-section {
  margin-top: 4px;
}
.send-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--el-text-color-primary);
}
.send-input {
  width: 220px;
}
.hex-form-item :deep(.el-form-item__content) {
  line-height: 32px;
}
.hex-inline {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.escape-label {
  user-select: none;
}
.hex-label {
  cursor: pointer;
  user-select: none;
}
.hex-checkbox {
  height: 32px;
  display: inline-flex;
  align-items: center;
}
.hex-checkbox :deep(.el-checkbox__inner) {
  width: 16px;
  height: 16px;
}
.hex-checkbox :deep(.el-checkbox__input) {
  transform: scale(1.05);
}
.line-ending-select {
  width: 82px;
}
.line-ending-select :deep(.el-select__wrapper) {
  padding-left: 4px;
  padding-right: 16px;
}
.port-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
