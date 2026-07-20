<template>
  <div class="app-container control-page">
    <el-card shadow="never" class="main-card">
      <template #header><span>设备连接</span></template>
      <div class="device-stack">
        <!-- CAN：左连接/发送，右独立接收 -->
        <el-row :gutter="12" class="device-block">
          <el-col :xs="24" :md="11" :lg="10">
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
                  <el-button type="primary" plain icon="Refresh" :loading="canRefreshing" :disabled="canConnected" @click="() => refreshCanVendors(true)">刷新</el-button>
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
                <el-button type="primary" :disabled="canConnected || canForm.vendor == null || canOpening" :loading="canOpening" @click="handleOpenCan">打开</el-button>
                <el-button :disabled="!canConnected || canOpening" @click="handleCloseCan">关闭</el-button>
                <el-tag :type="canConnected ? 'success' : 'info'" style="margin-left: 12px">
                  {{ canConnected ? '已连接' : '未连接' }} {{ activeDeviceId || '' }}
                </el-tag>
              </el-form-item>
              <el-form-item label="解释器">
                <div class="port-row">
                  <el-select v-model="canParserId" clearable placeholder="不绑定则不解析遥测" style="width: 220px" :disabled="!canConnected">
                    <el-option v-for="p in parserOptions" :key="p.id" :label="`${p.id} · ${p.name}`" :value="p.id" />
                  </el-select>
                  <el-button type="primary" plain :disabled="!canConnected" @click="handleBindCanParser">应用绑定</el-button>
                </div>
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
          <el-col :xs="24" :md="13" :lg="14">
            <el-card shadow="never" class="recv-card">
              <template #header><span>CAN接收</span></template>
              <IoLogPanel ref="canIoLogRef" :device-id="activeDeviceId" log-style="default" hex-only />
            </el-card>
          </el-col>
        </el-row>

        <!-- 串口 -->
        <el-row :gutter="12" class="device-block">
          <el-col :xs="24" :md="11" :lg="10">
          <el-card shadow="never" class="device-card">
            <template #header><span>串口连接</span></template>
            <el-form label-width="100px" class="control-form">
              <el-form-item label="串口号">
                <div class="port-row">
                  <el-select v-model="serialForm.port" filterable :disabled="serialConnected" style="width: 220px">
                    <el-option v-for="p in serialPorts" :key="p.port" :label="formatPortLabel(p)" :value="p.port" />
                  </el-select>
                  <el-button type="primary" plain icon="Refresh" :loading="serialRefreshing" :disabled="serialConnected" @click="refreshSerialPorts">刷新</el-button>
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
                <el-button type="primary" :disabled="serialConnected" @click="handleOpenSerial">打开</el-button>
                <el-button :disabled="!serialConnected" @click="handleCloseSerial">关闭</el-button>
                <el-tag :type="serialConnected ? 'success' : 'info'" style="margin-left: 12px">
                  {{ serialConnected ? '已连接' : '未连接' }} {{ serialDeviceId || '' }}
                </el-tag>
              </el-form-item>
              <el-divider />
              <RawDataSendPanel
                v-model="serialSend"
                title="串口发送"
                :disabled="!serialConnected"
                @send="sendSerialRaw"
              />
            </el-form>
          </el-card>
          </el-col>
          <el-col :xs="24" :md="13" :lg="14">
            <el-card shadow="never" class="recv-card">
              <template #header><span>串口接收</span></template>
              <IoLogPanel ref="serialIoLogRef" :device-id="serialDeviceId" log-style="default" />
            </el-card>
          </el-col>
        </el-row>

        <!-- UDP -->
        <el-row :gutter="12" class="device-block">
          <el-col :xs="24" :md="11" :lg="10">
          <el-card shadow="never" class="device-card">
            <template #header><span>UDP连接</span></template>
            <el-form label-width="100px" class="control-form">
              <el-form-item label="本机地址">
                <div class="port-row">
                  <el-select v-model="udpForm.localHost" filterable allow-create default-first-option :disabled="udpConnected" style="width: 220px">
                    <el-option v-for="a in localAddresses" :key="a" :label="a" :value="a" />
                  </el-select>
                  <el-button type="primary" plain icon="Refresh" :loading="udpAddrRefreshing" :disabled="udpConnected" @click="refreshLocalAddresses">刷新</el-button>
                </div>
              </el-form-item>
              <el-form-item label="本机端口">
                <el-input-number v-model="udpForm.localPort" :disabled="udpConnected" :min="1" :max="65535" style="width: 220px" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :disabled="udpConnected" @click="handleOpenUdp">打开</el-button>
                <el-button :disabled="!udpConnected" @click="handleCloseUdp">关闭</el-button>
                <el-tag :type="udpConnected ? 'success' : 'info'" style="margin-left: 12px">
                  {{ udpConnected ? '已连接' : '未连接' }} {{ udpDeviceId || '' }}
                </el-tag>
              </el-form-item>
              <el-divider />
              <RawDataSendPanel v-model="udpSend" title="UDP发送" :disabled="!udpConnected" @send="sendUdpRaw">
                <template #before>
                  <el-form-item label="远程地址">
                    <el-input v-model="udpRemoteHost" :disabled="!udpConnected" placeholder="如 192.168.1.10" style="width: 220px" />
                  </el-form-item>
                  <el-form-item label="远程端口">
                    <el-input-number v-model="udpRemotePort" :disabled="!udpConnected" :min="1" :max="65535" controls-position="right" style="width: 220px" />
                  </el-form-item>
                </template>
              </RawDataSendPanel>
            </el-form>
          </el-card>
          </el-col>
          <el-col :xs="24" :md="13" :lg="14">
            <el-card shadow="never" class="recv-card">
              <template #header><span>UDP接收</span></template>
              <IoLogPanel ref="udpIoLogRef" :device-id="udpDeviceId" log-style="udp" />
            </el-card>
          </el-col>
        </el-row>
      </div>
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
import RawDataSendPanel from '@/components/Payload/RawDataSendPanel.vue'
import IoLogPanel from '@/components/Payload/IoLogPanel.vue'
import {
  openCanChannel,
  closeCanChannel,
  listCanVendors,
  listCanChannels,
  listSerialPorts,
  listSerialOpened,
  openSerialPort,
  closeSerialPort,
  listLocalAddresses,
  listNetOpened,
  openNet,
  closeNet,
  getDeviceStatus,
  listParsers,
  bindDeviceParser
} from '@/api/payload/device'
import { sendCanRaw as sendCanRawApi, telecontrolControlOp, sendTelecontrol } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import { getTelemetryTable } from '@/api/payload/telemetry'
import { HEX_INPUT_WARN, isHexText, normalizeHexDisplay } from '@/utils/payloadRawData'

const ACTIVE_KEY = 'payload:activeDeviceId'
const SERIAL_ACTIVE_KEY = 'payload:serialDeviceId'
const UDP_ACTIVE_KEY = 'payload:udpDeviceId'
const CAN_PREFS_KEY = 'payload:control:canPrefs'
const SERIAL_PREFS_KEY = 'payload:control:serialPrefs'
const UDP_PREFS_KEY = 'payload:control:udpPrefs'

const canIoLogRef = ref(null)
const serialIoLogRef = ref(null)
const udpIoLogRef = ref(null)

function readPrefs(key) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : null
  } catch {
    return null
  }
}

function writePrefs(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify(data))
  } catch {
    /* ignore quota */
  }
}

/** 下拉：历史值在选项中则选中，否则用默认值 */
function pickOption(saved, options, getValue, fallback) {
  const list = options || []
  if (saved == null || saved === '') return fallback
  const hit = list.some(o => getValue(o) === saved)
  return hit ? saved : fallback
}

const canVendors = ref([])
const canRefreshing = ref(false)
const canVendorSelectKey = ref(0)
const canIndexOptions = [{ value: 0, label: '0' }, { value: 1, label: '1' }]
const baudOptions = [
  { value: 1000, label: '1000kbps' }, { value: 800, label: '800kbps' }, { value: 500, label: '500kbps' },
  { value: 250, label: '250kbps' }, { value: 125, label: '125kbps' }, { value: 100, label: '100kbps' },
  { value: 50, label: '50kbps' }, { value: 20, label: '20kbps' }, { value: 10, label: '10kbps' }, { value: 5, label: '5kbps' }
]
const cableOptions = [{ value: 0, label: '0 = 线A' }, { value: 1, label: '1 = 线B' }]
const nodeAddrOptions = [
  { value: 0x0D, label: '0x0D = 激光终端A' },
  { value: 0x0E, label: '0x0E = 激光终端B' }
]
const canForm = reactive({ vendor: null, devIndex: 0, canIndex: 0, baudRate: 500, nodeAddrTo: 0x0D, cableFlag: 0 })
const canSend = reactive({ frameIdHex: '00000000', dataHex: '00 01 02 03 04 05 06 07' })
const activeDeviceId = ref(localStorage.getItem(ACTIVE_KEY) || '')
const canConnected = ref(false)
const canOpening = ref(false)
const parserOptions = ref([])
const canParserId = ref('tm_can_yc')
const canPrefsLoaded = readPrefs(CAN_PREFS_KEY)

const serialRefreshing = ref(false)
const serialPorts = ref([])
const serialConnected = ref(false)
const serialDeviceId = ref(localStorage.getItem(SERIAL_ACTIVE_KEY) || '')
const serialBaudChoices = [
  110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200, 128000,
  230400, 256000, 460800, 921600, 1000000, 2000000
].map(v => ({ value: v, label: String(v) })).concat([{ value: 'custom', label: 'Customize' }])
const dataBitsOptions = [5, 6, 7, 8]
const stopBitsOptions = [1, 1.5, 2]
const parityOptions = [
  { value: 'N', label: 'NONE' }, { value: 'E', label: 'EVEN' }, { value: 'O', label: 'ODD' },
  { value: 'M', label: 'MARK' }, { value: 'S', label: 'SPACE' }
]
const flowOptions = [
  { value: 'NONE', label: 'NONE' }, { value: 'XON/XOFF', label: 'XON/XOFF' },
  { value: 'RTS/CTS', label: 'RTS/CTS' }, { value: 'DTR/DSR', label: 'DTR/DSR' },
  { value: 'RTS/CTS/XON/XOFF', label: 'RTS/CTS/XON/XOFF' }, { value: 'DTR/DSR/XON/XOFF', label: 'DTR/DSR/XON/XOFF' }
]
const serialForm = reactive({
  port: '', baudChoice: 9600, baudrate: 9600, dataBits: 8, stopBits: 1, parity: 'N', flowControl: 'NONE'
})
const serialSend = ref({ text: '', isHex: false, parseEscape: false, lineEnding: 'none' })
const serialPrefsLoaded = readPrefs(SERIAL_PREFS_KEY)

const udpAddrRefreshing = ref(false)
const localAddresses = ref(['0.0.0.0', '127.0.0.1'])
const udpConnected = ref(false)
const udpDeviceId = ref(localStorage.getItem(UDP_ACTIVE_KEY) || '')
const udpForm = reactive({ localHost: '0.0.0.0', localPort: 9000 })
const udpRemoteHost = ref('')
const udpRemotePort = ref(9000)
const udpSend = ref({ text: '', isHex: false, parseEscape: false, lineEnding: 'none' })
const udpPrefsLoaded = readPrefs(UDP_PREFS_KEY)

function applyCanPrefsFromStorage() {
  const p = canPrefsLoaded
  if (!p) return
  if (p.devIndex != null) canForm.devIndex = Number(p.devIndex)
  if (p.canIndex != null) canForm.canIndex = Number(p.canIndex)
  if (p.baudRate != null) {
    canForm.baudRate = pickOption(Number(p.baudRate), baudOptions, o => o.value, 500)
  }
  if (p.cableFlag != null) {
    canForm.cableFlag = pickOption(Number(p.cableFlag), cableOptions, o => o.value, 0)
  }
  if (p.nodeAddrTo != null) {
    canForm.nodeAddrTo = pickOption(Number(p.nodeAddrTo), nodeAddrOptions, o => o.value, 0x0D)
  }
  if (p.parserId !== undefined) canParserId.value = p.parserId || ''
  // vendor 等厂商列表加载后再对一下
  if (p.vendor != null) canForm.vendor = Number(p.vendor)
}

function applySerialPrefsFromStorage() {
  const p = serialPrefsLoaded
  if (!p) return
  if (p.port) serialForm.port = String(p.port)
  if (p.baudChoice !== undefined && p.baudChoice !== null) {
    const choice = p.baudChoice === 'custom' ? 'custom' : Number(p.baudChoice)
    serialForm.baudChoice = pickOption(choice, serialBaudChoices, o => o.value, 9600)
  }
  if (p.baudrate != null) serialForm.baudrate = Number(p.baudrate) || 9600
  if (p.dataBits != null) {
    serialForm.dataBits = pickOption(Number(p.dataBits), dataBitsOptions.map(d => ({ value: d })), o => o.value, 8)
  }
  if (p.stopBits != null) {
    serialForm.stopBits = pickOption(Number(p.stopBits), stopBitsOptions.map(d => ({ value: d })), o => o.value, 1)
  }
  if (p.parity) {
    serialForm.parity = pickOption(String(p.parity), parityOptions, o => o.value, 'N')
  }
  if (p.flowControl) {
    serialForm.flowControl = pickOption(String(p.flowControl), flowOptions, o => o.value, 'NONE')
  }
}

function applyUdpPrefsFromStorage() {
  const p = udpPrefsLoaded
  if (!p) return
  if (p.localHost) udpForm.localHost = String(p.localHost)
  if (p.localPort != null) {
    const port = Number(p.localPort)
    udpForm.localPort = Number.isFinite(port) && port > 0 ? port : 9000
  }
  if (p.remoteHost != null) {
    const rh = String(p.remoteHost || '')
    // 兼容旧版 host:port 单字段
    const idx = rh.lastIndexOf(':')
    if (idx > 0 && p.remotePort == null) {
      const host = rh.slice(0, idx).trim()
      const port = Number(rh.slice(idx + 1))
      udpRemoteHost.value = host
      if (Number.isFinite(port) && port > 0) udpRemotePort.value = port
    } else {
      udpRemoteHost.value = rh
    }
  }
  if (p.remotePort != null) {
    const port = Number(p.remotePort)
    if (Number.isFinite(port) && port > 0) udpRemotePort.value = port
  }
}

function saveCanPrefs() {
  writePrefs(CAN_PREFS_KEY, {
    vendor: canForm.vendor,
    devIndex: canForm.devIndex,
    canIndex: canForm.canIndex,
    baudRate: canForm.baudRate,
    cableFlag: canForm.cableFlag,
    nodeAddrTo: canForm.nodeAddrTo,
    parserId: canParserId.value || ''
  })
}

function saveSerialPrefs() {
  writePrefs(SERIAL_PREFS_KEY, {
    port: serialForm.port,
    baudChoice: serialForm.baudChoice,
    baudrate: serialForm.baudrate,
    dataBits: serialForm.dataBits,
    stopBits: serialForm.stopBits,
    parity: serialForm.parity,
    flowControl: serialForm.flowControl
  })
}

function saveUdpPrefs() {
  writePrefs(UDP_PREFS_KEY, {
    localHost: udpForm.localHost,
    localPort: udpForm.localPort,
    remoteHost: udpRemoteHost.value || '',
    remotePort: udpRemotePort.value || 0
  })
}

applyCanPrefsFromStorage()
applySerialPrefsFromStorage()
applyUdpPrefsFromStorage()

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
  return (raw || []).map(v => ({ value: v.value, key: v.key, name: v.name }))
}
function isPcieVendor(v) {
  return `${v.key || ''} ${v.name || ''}`.toUpperCase().includes('PCIE')
}
function pickDefaultVendor(vendors) {
  if (!vendors.length) return null
  return (vendors.find(isPcieVendor) || vendors[0]).value
}

async function refreshCanVendors(showMsg = false) {
  if (canRefreshing.value) return
  canRefreshing.value = true
  const preferred = canForm.vendor ?? canPrefsLoaded?.vendor ?? null
  try {
    const res = await listCanVendors()
    const nextVendors = mapCanVendors(res.data?.vendors)
    canVendors.value = nextVendors
    canVendorSelectKey.value += 1
    if (!canConnected.value) {
      canForm.vendor = pickOption(
        preferred != null ? Number(preferred) : null,
        nextVendors,
        v => v.value,
        pickDefaultVendor(nextVendors)
      )
    }
    if (showMsg) ElMessage.success(`已刷新，发现 ${nextVendors.length} 个厂商`)
  } catch {
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
  const preferred = serialForm.port || serialPrefsLoaded?.port || ''
  try {
    const res = await listSerialPorts()
    serialPorts.value = res.data || []
    if (!serialConnected.value) {
      if (serialPorts.value.length) {
        serialForm.port = pickOption(preferred, serialPorts.value, p => p.port, serialPorts.value[0].port)
      } else {
        serialForm.port = ''
      }
    }
    if (showMsg) ElMessage.success(`已刷新，发现 ${serialPorts.value.length} 个串口`)
  } catch {
    if (showMsg) ElMessage.error('刷新串口列表失败')
  } finally {
    serialRefreshing.value = false
  }
}

async function refreshLocalAddresses(showMsg = true) {
  if (udpAddrRefreshing.value) return
  udpAddrRefreshing.value = true
  const preferred = udpForm.localHost || udpPrefsLoaded?.localHost || '0.0.0.0'
  try {
    const res = await listLocalAddresses()
    localAddresses.value = res.data?.length ? res.data : ['0.0.0.0', '127.0.0.1']
    if (!udpConnected.value) {
      // 在列表中则选中；不在列表则回默认（allow-create 仍可手改）
      udpForm.localHost = pickOption(preferred, localAddresses.value.map(a => ({ value: a })), o => o.value, '0.0.0.0')
    }
    if (showMsg) ElMessage.success(`已刷新，发现 ${localAddresses.value.length} 个地址`)
  } catch {
    if (showMsg) ElMessage.error('刷新本机地址失败')
  } finally {
    udpAddrRefreshing.value = false
  }
}

async function loadParsers() {
  try {
    const res = await listParsers()
    parserOptions.value = res.data || []
  } catch {
    parserOptions.value = [{ id: 'tm_can_yc', name: 'CAN遥测复合帧(TeleMetryCfg)', dataKind: 'tm' }]
  }
  const saved = canPrefsLoaded?.parserId
  if (saved === '') {
    canParserId.value = ''
  } else {
    canParserId.value = pickOption(saved || 'tm_can_yc', parserOptions.value, p => p.id, 'tm_can_yc')
  }
}

async function handleBindCanParser() {
  if (!activeDeviceId.value) return ElMessage.warning('请先打开 CAN 通道')
  await bindDeviceParser({ srcParam: activeDeviceId.value, srcKind: 'can', parserId: canParserId.value || '' })
  ElMessage.success(canParserId.value ? `已绑定 ${canParserId.value}` : '已解绑解释器（将不再解析遥测）')
}

async function handleOpenCan() {
  if (canForm.vendor == null || canOpening.value) return
  canOpening.value = true
  try {
    const res = await openCanChannel({ ...canForm, parserId: canParserId.value || '' })
    activeDeviceId.value = res.data.deviceId
    localStorage.setItem(ACTIVE_KEY, activeDeviceId.value)
    canConnected.value = true
    const pid = res.data?.session?.parserId
    if (pid !== undefined) canParserId.value = pid || ''
    saveCanPrefs()
    ElMessage.success('CAN 通道已打开')
  } catch {
    canConnected.value = false
    activeDeviceId.value = ''
    localStorage.removeItem(ACTIVE_KEY)
  } finally {
    canOpening.value = false
  }
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
  try {
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
    saveSerialPrefs()
    ElMessage.success('串口已打开')
  } catch {
    serialConnected.value = false
    serialDeviceId.value = ''
    localStorage.removeItem(SERIAL_ACTIVE_KEY)
  }
}

async function handleCloseSerial() {
  if (!serialForm.port) return
  await closeSerialPort(serialForm.port)
  serialConnected.value = false
  serialDeviceId.value = ''
  localStorage.removeItem(SERIAL_ACTIVE_KEY)
  ElMessage.success('串口已关闭')
}

async function handleOpenUdp() {
  if (!udpForm.localHost || !udpForm.localPort) return ElMessage.warning('请填写本机地址和端口')
  try {
    const res = await openNet({
      proto: 'udp',
      localHost: udpForm.localHost,
      localPort: udpForm.localPort
    })
    udpDeviceId.value = res.data.deviceId
    localStorage.setItem(UDP_ACTIVE_KEY, udpDeviceId.value)
    udpConnected.value = true
    saveUdpPrefs()
    ElMessage.success('UDP 已打开')
  } catch {
    udpConnected.value = false
    udpDeviceId.value = ''
    localStorage.removeItem(UDP_ACTIVE_KEY)
  }
}

async function handleCloseUdp() {
  await closeNet({ proto: 'udp', localHost: udpForm.localHost, localPort: udpForm.localPort })
  udpConnected.value = false
  udpDeviceId.value = ''
  localStorage.removeItem(UDP_ACTIVE_KEY)
  ElMessage.success('UDP 已关闭')
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

async function sendCanRaw() {
  if (!activeDeviceId.value) return
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
      deviceId: activeDeviceId.value,
      frameIdHex: frameIdPadded,
      dataHex: String(canSend.dataHex || '')
    })
    notifyPayloadSendResult(res, { deviceId: activeDeviceId.value, channel: 'CAN' })
    canIoLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function sendSerialRaw(hex) {
  if (!serialDeviceId.value) return
  try {
    const res = await sendTelecontrol({
      deviceId: serialDeviceId.value,
      name: 'SERIAL_RAW',
      hex,
      displayHex: !!serialSend.value.isHex
    })
    notifyPayloadSendResult(res, { deviceId: serialDeviceId.value, channel: '串口' })
    serialIoLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function sendUdpRaw(hex) {
  if (!udpDeviceId.value) return
  const host = String(udpRemoteHost.value || '').trim()
  const port = Number(udpRemotePort.value)
  if (!host) return ElMessage.warning('请填写远程地址')
  if (!Number.isFinite(port) || port <= 0 || port > 65535) return ElMessage.warning('请填写有效远程端口')
  try {
    const res = await sendTelecontrol({
      deviceId: udpDeviceId.value,
      name: 'UDP_RAW',
      hex,
      remoteHost: host,
      remotePort: port,
      displayHex: !!udpSend.value.isHex
    })
    notifyPayloadSendResult(res, { deviceId: udpDeviceId.value, channel: 'UDP' })
    udpIoLogRef.value?.pullOnce()
  } catch { /* interceptor */ }
}

async function op(name, params = {}) {
  if (!activeDeviceId.value) return ElMessage.warning('请先打开 CAN 通道')
  try {
    const res = await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
    notifyPayloadSendResult(res, { deviceId: activeDeviceId.value, channel: 'CAN' })
  } catch { /* interceptor */ }
}

function applySerialOpened(s) {
  serialDeviceId.value = s.deviceId
  localStorage.setItem(SERIAL_ACTIVE_KEY, s.deviceId)
  serialForm.port = s.port
  if (s.baudrate != null) {
    const baud = Number(s.baudrate)
    serialForm.baudChoice = serialBaudChoices.some(b => b.value === baud) ? baud : 'custom'
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
      try {
        const st = await getDeviceStatus(ch.deviceId)
        canParserId.value = st.data?.parserId || ''
      } catch { /* ignore */ }
    } else if (activeDeviceId.value) {
      const st = await getDeviceStatus(activeDeviceId.value)
      canConnected.value = !!st.data?.connected
      canParserId.value = st.data?.parserId || ''
      if (!canConnected.value) {
        activeDeviceId.value = ''
        localStorage.removeItem(ACTIVE_KEY)
      }
    }

    const serialRes = await listSerialOpened()
    const aliveSerial = (serialRes.data || []).filter(s => s.alive)
    if (aliveSerial.length) {
      applySerialOpened(aliveSerial.find(x => x.deviceId === serialDeviceId.value) || aliveSerial[0])
    } else if (serialDeviceId.value) {
      const st = await getDeviceStatus(serialDeviceId.value)
      serialConnected.value = !!st.data?.connected
      if (!serialConnected.value) {
        serialDeviceId.value = ''
        localStorage.removeItem(SERIAL_ACTIVE_KEY)
      }
    }

    const netRes = await listNetOpened()
    const aliveNet = (netRes.data || []).filter(n => n.alive)
    if (aliveNet.length) {
      const n = aliveNet.find(x => x.deviceId === udpDeviceId.value) || aliveNet[0]
      udpDeviceId.value = n.deviceId
      localStorage.setItem(UDP_ACTIVE_KEY, n.deviceId)
      udpForm.localHost = n.localHost || udpForm.localHost
      udpForm.localPort = n.localPort || udpForm.localPort
      if (n.remoteHost) udpRemoteHost.value = String(n.remoteHost)
      if (n.remotePort) udpRemotePort.value = Number(n.remotePort)
      udpConnected.value = true
    } else if (udpDeviceId.value) {
      const st = await getDeviceStatus(udpDeviceId.value)
      udpConnected.value = !!st.data?.connected
      if (!udpConnected.value) {
        udpDeviceId.value = ''
        localStorage.removeItem(UDP_ACTIVE_KEY)
      }
    }

  } catch { /* ignore */ }
}

async function pollStatus() {
  try {
    if (activeDeviceId.value) {
      const st = await getDeviceStatus(activeDeviceId.value)
      const wasConnected = canConnected.value
      canConnected.value = !!st.data?.connected
      if (!canConnected.value) {
        activeDeviceId.value = ''
        localStorage.removeItem(ACTIVE_KEY)
        if (wasConnected) ElMessage.warning('CAN 连接已断开（采集进程退出或通道已关闭）')
      } else {
        try {
          const tm = await getTelemetryTable('FF')
          const rows = tm.data?.rows || []
          const find = id => rows.find(r => r.id === id)?.show || '0'
          rateInfo.time = find('JGB132')
          rateInfo.speed = find('JGB133')
          rateInfo.err = find('JGB135')
        } catch { /* ignore */ }
      }
    }
    if (serialDeviceId.value) {
      const st = await getDeviceStatus(serialDeviceId.value)
      const wasConnected = serialConnected.value
      serialConnected.value = !!st.data?.connected
      if (!serialConnected.value) {
        serialDeviceId.value = ''
        localStorage.removeItem(SERIAL_ACTIVE_KEY)
        if (wasConnected) ElMessage.warning('串口连接已断开')
      }
    }
    if (udpDeviceId.value) {
      const st = await getDeviceStatus(udpDeviceId.value)
      const wasConnected = udpConnected.value
      udpConnected.value = !!st.data?.connected
      if (!udpConnected.value) {
        udpDeviceId.value = ''
        localStorage.removeItem(UDP_ACTIVE_KEY)
        if (wasConnected) ElMessage.warning('UDP 连接已断开')
      }
    }
  } catch { /* ignore */ }
}

onMounted(async () => {
  // 表单已从 localStorage 预填；再拉选项并对齐下拉
  await loadParsers()
  await refreshCanVendors(false)
  await refreshSerialPorts(false)
  await refreshLocalAddresses(false)
  await restoreConnectionState()
  pollStatus()
  statusTimer = setInterval(pollStatus, 2000)
})
onUnmounted(() => clearInterval(statusTimer))
</script>

<style scoped>
.device-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.device-block {
  align-items: stretch;
}
.recv-card {
  width: 100%;
  height: 100%;
  min-height: 320px;
  display: flex;
  flex-direction: column;
}
.recv-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.control-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.send-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}
.send-input {
  width: 100%;
  max-width: 320px;
}
.port-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
