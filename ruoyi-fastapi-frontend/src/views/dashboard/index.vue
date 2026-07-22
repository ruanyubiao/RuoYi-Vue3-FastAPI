<template>
  <div class="app-container device-service-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>设备服务</span>
          <div class="head-actions">
            <el-button type="primary" plain :loading="loading" @click="refresh(true)">刷新</el-button>
            <el-checkbox v-model="autoRefresh">自动刷新</el-checkbox>
          </div>
        </div>
      </template>

      <div class="hint">当前已打开的 CAN / 串口 / UDP 监听服务。可在此绑定/修改解释器并关闭连接。</div>

      <el-table :data="rows" stripe empty-text="暂无已打开的设备服务">
        <el-table-column label="类型" prop="kindLabel" width="90" align="center" />
        <el-table-column label="设备 ID" prop="deviceId" min-width="200" show-overflow-tooltip />
        <el-table-column label="连接信息" prop="detail" min-width="220" show-overflow-tooltip />
        <el-table-column label="解释器" prop="parserId" min-width="180" align="center">
          <template #default="{ row }">
            <span v-if="row.parserId">{{ parserLabel(row.parserId) }}</span>
            <span v-else class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="打开时间" prop="openedAt" width="170" align="center" />
        <el-table-column label="操作" width="180" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBindParser(row)">修改</el-button>
            <el-button
              link
              type="danger"
              :loading="row.closing"
              @click="handleClose(row)"
            >
              关闭连接
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="create-card">
      <template #header><span>新建连接</span></template>
      <div class="create-actions">
        <el-button type="primary" @click="openCreate('can')">新建 CAN 连接</el-button>
        <el-button type="primary" @click="openCreate('udp')">新建 UDP 连接</el-button>
        <el-button type="primary" @click="openCreate('serial')">新建串口连接</el-button>
      </div>
    </el-card>

    <!-- CAN -->
    <el-dialog v-model="dlg.can" title="新建 CAN 连接" width="520px" destroy-on-close @opened="onCanOpened">
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="厂商">
          <div class="port-row">
            <el-select
              :key="canVendorSelectKey"
              v-model="canForm.vendor"
              :disabled="canOpening"
              placeholder="请选择厂商"
              class="conn-ctrl"
            >
              <el-option
                v-for="v in canVendors"
                :key="`${v.value}-${v.name}`"
                :label="formatCanVendorLabel(v)"
                :value="v.value"
              />
            </el-select>
            <el-button type="primary" plain icon="Refresh" :loading="canRefreshing" :disabled="canOpening" @click="refreshCanVendors">
              刷新
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="设备索引号">
          <el-select v-model="canForm.devIndex" :disabled="canOpening" class="conn-ctrl">
            <el-option :label="'0'" :value="0" />
          </el-select>
        </el-form-item>
        <el-form-item label="通道号">
          <el-select v-model="canForm.canIndex" :disabled="canOpening" class="conn-ctrl">
            <el-option v-for="ch in canIndexOptions" :key="ch.value" :label="ch.label" :value="ch.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="波特率">
          <el-select v-model="canForm.baudRate" :disabled="canOpening" class="conn-ctrl">
            <el-option v-for="b in baudOptions" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="线缆">
          <el-select v-model="canForm.cableFlag" :disabled="canOpening" class="conn-ctrl">
            <el-option v-for="c in cableOptions" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标地址">
          <el-select v-model="canForm.nodeAddrTo" :disabled="canOpening" class="conn-ctrl">
            <el-option v-for="n in nodeAddrOptions" :key="n.value" :label="n.label" :value="n.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="canParserId" clearable placeholder="请选择解释器" class="conn-ctrl" :disabled="canOpening">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="field-tip">不绑定则不解析数据</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="canOpening" :disabled="canForm.vendor == null" @click="submitCan">打开</el-button>
          <el-button @click="dlg.can = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>

    <!-- UDP -->
    <el-dialog v-model="dlg.udp" title="新建 UDP 连接" width="520px" destroy-on-close @opened="onUdpOpened">
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="本机地址">
          <div class="port-row">
            <el-select
              v-model="udpForm.localHost"
              filterable
              allow-create
              default-first-option
              :disabled="udpOpening"
              class="conn-ctrl"
            >
              <el-option v-for="a in localAddresses" :key="a" :label="a" :value="a" />
            </el-select>
            <el-button type="primary" plain icon="Refresh" :loading="udpAddrRefreshing" :disabled="udpOpening" @click="refreshLocalAddresses">
              刷新
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="本机端口">
          <el-input-number v-model="udpForm.localPort" :disabled="udpOpening" :min="1" :max="65535" class="conn-ctrl" controls-position="right" />
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="udpParserId" clearable placeholder="请选择解释器" class="conn-ctrl" :disabled="udpOpening">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="field-tip">不绑定则不解析数据</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="udpOpening" :disabled="!udpForm.localHost || !udpForm.localPort" @click="submitUdp">
            打开
          </el-button>
          <el-button @click="dlg.udp = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>

    <!-- 串口 -->
    <el-dialog v-model="dlg.serial" title="新建串口连接" width="560px" destroy-on-close @opened="onSerialOpened">
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="串口号">
          <div class="port-row">
            <el-select v-model="serialForm.port" filterable :disabled="serialOpening" class="conn-ctrl">
              <el-option v-for="p in serialPorts" :key="p.port" :label="formatPortLabel(p)" :value="p.port" />
            </el-select>
            <el-button type="primary" plain icon="Refresh" :loading="serialRefreshing" :disabled="serialOpening" @click="refreshSerialPorts">
              刷新
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="波特率">
          <el-select v-model="serialForm.baudChoice" :disabled="serialOpening" class="conn-ctrl">
            <el-option v-for="b in serialBaudChoices" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
          <el-input-number
            v-if="serialForm.baudChoice === 'custom'"
            v-model="serialForm.baudrate"
            :disabled="serialOpening"
            :min="110"
            :step="100"
            class="conn-ctrl conn-ctrl--gap"
          />
        </el-form-item>
        <el-form-item label="数据位">
          <el-select v-model="serialForm.dataBits" :disabled="serialOpening" class="conn-ctrl">
            <el-option v-for="d in dataBitsOptions" :key="d" :label="String(d)" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="停止位">
          <el-select v-model="serialForm.stopBits" :disabled="serialOpening" class="conn-ctrl">
            <el-option v-for="s in stopBitsOptions" :key="s" :label="String(s)" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="校验位">
          <el-select v-model="serialForm.parity" :disabled="serialOpening" class="conn-ctrl">
            <el-option v-for="p in parityOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="流控制">
          <el-select v-model="serialForm.flowControl" :disabled="serialOpening" class="conn-ctrl">
            <el-option v-for="f in flowOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="serialParserId" clearable placeholder="请选择解释器" class="conn-ctrl" :disabled="serialOpening">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="field-tip">不绑定则不解析数据</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="serialOpening" :disabled="!serialForm.port" @click="submitSerial">打开</el-button>
          <el-button @click="dlg.serial = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
    <!-- 修改解释器 -->
    <el-dialog v-model="dlg.bind" title="修改解释器绑定" width="480px" destroy-on-close>
      <el-form label-width="100px" class="conn-form">
        <el-form-item label="设备">
          <span>{{ bindForm.kindLabel }} · {{ bindForm.deviceId }}</span>
        </el-form-item>
        <el-form-item label="连接信息">
          <span class="bind-detail">{{ bindForm.detail || '—' }}</span>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select
            v-model="bindForm.parserId"
            clearable
            placeholder="请选择解释器"
            class="conn-ctrl"
            :disabled="bindSaving"
          >
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="field-tip">清空并保存表示解绑；不绑定则不解析数据</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="bindSaving" @click="submitBindParser">保存</el-button>
          <el-button :disabled="bindSaving" @click="dlg.bind = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup name="Index">
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listCanChannels,
  listSerialOpened,
  listNetOpened,
  listDeviceSessions,
  closeCanChannel,
  closeSerialPort,
  closeNet,
  listCanVendors,
  listSerialPorts,
  listLocalAddresses,
  listParsers,
  openCanChannel,
  openSerialPort,
  openNet,
  bindDeviceParser
} from '@/api/payload/device'

const ACTIVE_KEY = 'payload:activeDeviceId'
const SERIAL_ACTIVE_KEY = 'payload:serialDeviceId'
const UDP_ACTIVE_KEY = 'payload:udpDeviceId'
const CAN_PREFS_KEY = 'payload:control:canPrefs'
const SERIAL_PREFS_KEY = 'payload:control:serialPrefs'
const UDP_PREFS_KEY = 'payload:control:udpPrefs'

const loading = ref(false)
const autoRefresh = ref(true)
const rows = ref([])
let timer = null
let refreshing = false

const KIND_LABEL = { can: 'CAN', serial: '串口', udp: 'UDP' }

const dlg = reactive({ can: false, udp: false, serial: false, bind: false })
const parserOptions = ref([])
const bindSaving = ref(false)
const bindForm = reactive({
  deviceId: '',
  kind: '',
  kindLabel: '',
  detail: '',
  parserId: ''
})

const canVendors = ref([])
const canRefreshing = ref(false)
const canVendorSelectKey = ref(0)
const canOpening = ref(false)
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
const canForm = reactive({ vendor: null, devIndex: 0, canIndex: 0, baudRate: 500, nodeAddrTo: 0x0d, cableFlag: 0 })
const canParserId = ref('tm_can_yc')

const serialRefreshing = ref(false)
const serialOpening = ref(false)
const serialPorts = ref([])
const serialBaudChoices = [
  110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400, 56000, 57600, 115200, 128000, 230400, 256000, 460800,
  921600, 1000000, 2000000
]
  .map(v => ({ value: v, label: String(v) }))
  .concat([{ value: 'custom', label: 'Customize' }])
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
const serialParserId = ref('')

const udpAddrRefreshing = ref(false)
const udpOpening = ref(false)
const localAddresses = ref(['0.0.0.0', '127.0.0.1'])
const udpForm = reactive({ localHost: '0.0.0.0', localPort: 9000 })
const udpParserId = ref('')

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
    /* ignore */
  }
}

function pickOption(saved, options, getValue, fallback) {
  const list = options || []
  if (saved == null || saved === '') return fallback
  return list.some(o => getValue(o) === saved) ? saved : fallback
}

function formatPortLabel(p) {
  return p.description ? `${p.port} (${p.description})` : p.port
}
function formatCanVendorLabel(v) {
  return `${v.value} - ${v.name || ''}`
}
function isPcieVendor(v) {
  return `${v.key || ''} ${v.name || ''}`.toUpperCase().includes('PCIE')
}
function pickDefaultVendor(vendors) {
  if (!vendors.length) return null
  return (vendors.find(isPcieVendor) || vendors[0]).value
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

function applyCanPrefs() {
  const p = readPrefs(CAN_PREFS_KEY)
  if (!p) return
  if (p.devIndex != null) canForm.devIndex = Number(p.devIndex)
  if (p.canIndex != null) canForm.canIndex = Number(p.canIndex)
  if (p.baudRate != null) canForm.baudRate = pickOption(Number(p.baudRate), baudOptions, o => o.value, 500)
  if (p.cableFlag != null) canForm.cableFlag = pickOption(Number(p.cableFlag), cableOptions, o => o.value, 0)
  if (p.nodeAddrTo != null) canForm.nodeAddrTo = pickOption(Number(p.nodeAddrTo), nodeAddrOptions, o => o.value, 0x0d)
  if (p.parserId !== undefined) canParserId.value = p.parserId || ''
  if (p.vendor != null) canForm.vendor = Number(p.vendor)
}

function applySerialPrefs() {
  const p = readPrefs(SERIAL_PREFS_KEY)
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
  if (p.parity) serialForm.parity = pickOption(String(p.parity), parityOptions, o => o.value, 'N')
  if (p.flowControl) serialForm.flowControl = pickOption(String(p.flowControl), flowOptions, o => o.value, 'NONE')
  if (p.parserId !== undefined) serialParserId.value = p.parserId || ''
}

function applyUdpPrefs() {
  const p = readPrefs(UDP_PREFS_KEY)
  if (!p) return
  if (p.localHost) udpForm.localHost = String(p.localHost)
  if (p.localPort != null) {
    const port = Number(p.localPort)
    udpForm.localPort = Number.isFinite(port) && port > 0 ? port : 9000
  }
  if (p.parserId !== undefined) udpParserId.value = p.parserId || ''
}

async function refreshCanVendors() {
  canRefreshing.value = true
  try {
    const res = await listCanVendors()
    const list = mapCanVendors(res.data?.vendors || res.data || [])
    canVendors.value = list
    canVendorSelectKey.value += 1
    const saved = readPrefs(CAN_PREFS_KEY)?.vendor
    if (saved != null && list.some(v => v.value === Number(saved))) {
      canForm.vendor = Number(saved)
    } else if (canForm.vendor == null || !list.some(v => v.value === canForm.vendor)) {
      canForm.vendor = pickDefaultVendor(list)
    }
  } finally {
    canRefreshing.value = false
  }
}

function mapCanVendors(raw) {
  return (raw || []).map(v => ({ value: v.value, key: v.key, name: v.name }))
}

async function refreshSerialPorts() {
  serialRefreshing.value = true
  try {
    const res = await listSerialPorts()
    serialPorts.value = res.data || []
    if (serialForm.port && !serialPorts.value.some(p => p.port === serialForm.port)) {
      serialForm.port = serialPorts.value[0]?.port || ''
    } else if (!serialForm.port && serialPorts.value.length) {
      serialForm.port = serialPorts.value[0].port
    }
  } finally {
    serialRefreshing.value = false
  }
}

async function refreshLocalAddresses() {
  udpAddrRefreshing.value = true
  try {
    const res = await listLocalAddresses()
    const list = res.data || []
    localAddresses.value = list.length ? list : ['0.0.0.0', '127.0.0.1']
    if (!localAddresses.value.includes(udpForm.localHost)) {
      udpForm.localHost = localAddresses.value[0]
    }
  } finally {
    udpAddrRefreshing.value = false
  }
}

function openCreate(kind) {
  dlg.can = kind === 'can'
  dlg.udp = kind === 'udp'
  dlg.serial = kind === 'serial'
}

async function onCanOpened() {
  applyCanPrefs()
  await Promise.all([loadParsers(), refreshCanVendors()])
}

async function onUdpOpened() {
  applyUdpPrefs()
  await Promise.all([loadParsers(), refreshLocalAddresses()])
}

async function onSerialOpened() {
  applySerialPrefs()
  await Promise.all([loadParsers(), refreshSerialPorts()])
}

async function submitCan() {
  if (canForm.vendor == null || canOpening.value) return
  canOpening.value = true
  try {
    const res = await openCanChannel({ ...canForm, parserId: canParserId.value || '' })
    const deviceId = res.data?.deviceId
    if (deviceId) localStorage.setItem(ACTIVE_KEY, deviceId)
    writePrefs(CAN_PREFS_KEY, {
      vendor: canForm.vendor,
      devIndex: canForm.devIndex,
      canIndex: canForm.canIndex,
      baudRate: canForm.baudRate,
      cableFlag: canForm.cableFlag,
      nodeAddrTo: canForm.nodeAddrTo,
      parserId: canParserId.value || ''
    })
    if (res.data?.status === 'already_open') {
      ElMessage.error('设备已打开')
      return
    }
    ElMessage.success('CAN 通道已打开')
    dlg.can = false
    await refresh(false)
  } finally {
    canOpening.value = false
  }
}

async function submitUdp() {
  if (!udpForm.localHost || !udpForm.localPort || udpOpening.value) return
  udpOpening.value = true
  try {
    const res = await openNet({
      proto: 'udp',
      localHost: udpForm.localHost,
      localPort: udpForm.localPort,
      parserId: udpParserId.value || ''
    })
    const deviceId = res.data?.deviceId
    if (deviceId) localStorage.setItem(UDP_ACTIVE_KEY, deviceId)
    writePrefs(UDP_PREFS_KEY, {
      ...(readPrefs(UDP_PREFS_KEY) || {}),
      localHost: udpForm.localHost,
      localPort: udpForm.localPort,
      parserId: udpParserId.value || ''
    })
    if (res.data?.status === 'already_open') {
      ElMessage.error('设备已打开')
      return
    }
    ElMessage.success('UDP 已打开')
    dlg.udp = false
    await refresh(false)
  } finally {
    udpOpening.value = false
  }
}

async function submitSerial() {
  if (!serialForm.port || serialOpening.value) return
  if (serialForm.baudChoice !== 'custom') serialForm.baudrate = Number(serialForm.baudChoice)
  serialOpening.value = true
  try {
    const res = await openSerialPort({
      port: serialForm.port,
      baudrate: serialForm.baudrate,
      mode: 'raw',
      dataBits: serialForm.dataBits,
      stopBits: serialForm.stopBits,
      parity: serialForm.parity,
      flowControl: serialForm.flowControl,
      parserId: serialParserId.value || ''
    })
    const deviceId = res.data?.deviceId
    if (deviceId) localStorage.setItem(SERIAL_ACTIVE_KEY, deviceId)
    writePrefs(SERIAL_PREFS_KEY, {
      port: serialForm.port,
      baudChoice: serialForm.baudChoice,
      baudrate: serialForm.baudrate,
      dataBits: serialForm.dataBits,
      stopBits: serialForm.stopBits,
      parity: serialForm.parity,
      flowControl: serialForm.flowControl,
      parserId: serialParserId.value || ''
    })
    if (res.data?.status === 'already_open') {
      ElMessage.error('设备已打开')
      return
    }
    ElMessage.success('串口已打开')
    dlg.serial = false
    await refresh(false)
  } finally {
    serialOpening.value = false
  }
}

function sessionMap(sessions) {
  const map = new Map()
  for (const s of sessions || []) {
    if (s?.srcParam) map.set(s.srcParam, s)
  }
  return map
}

function parserLabel(parserId) {
  if (!parserId) return ''
  const hit = parserOptions.value.find(p => p.id === parserId)
  return hit?.name || parserId
}

function buildRows(canList, serialList, netList, sessions) {
  const sm = sessionMap(sessions)
  const out = []

  for (const d of canList || []) {
    if (d.demo || !d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    out.push({
      kind: 'can',
      kindLabel: KIND_LABEL.can,
      deviceId: sid,
      detail: `vendor=${d.vendor} · 卡${d.devIndex} · 通道${d.canIndex}`,
      parserId: sess.parserId || '',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: { vendor: d.vendor, devIndex: d.devIndex, canIndex: d.canIndex }
    })
  }

  for (const d of serialList || []) {
    if (!d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    const parity = String(d.parity || 'N').toUpperCase().slice(0, 1) || 'N'
    const flow = String(d.flowControl || 'NONE').toUpperCase()
    const bits = [
      d.port || sid,
      d.baudrate != null ? `${d.baudrate}bps` : null,
      d.dataBits != null ? `${d.dataBits}${parity}${d.stopBits ?? 1}` : null,
      // 默认无流控不展示；非 NONE 时补上，便于排查
      flow && flow !== 'NONE' ? `${d.flowControl}` : null
    ].filter(Boolean)
    out.push({
      kind: 'serial',
      kindLabel: KIND_LABEL.serial,
      deviceId: sid,
      detail: bits.join(' · '),
      parserId: sess.parserId || '',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: { port: d.port }
    })
  }

  for (const d of netList || []) {
    if (!d.alive) continue
    const sid = d.deviceId
    const sess = sm.get(sid) || {}
    const local = `${d.localHost || '?'}:${d.localPort ?? '?'}`
    const remote = d.remoteHost && d.remotePort ? ` → ${d.remoteHost}:${d.remotePort}` : ''
    out.push({
      kind: 'udp',
      kindLabel: KIND_LABEL.udp,
      deviceId: sid,
      detail: `${(d.proto || 'udp').toUpperCase()} ${local}${remote}`,
      parserId: sess.parserId || '',
      openedAt: sess.openedAt || '—',
      closing: false,
      closeArgs: {
        proto: d.proto || 'udp',
        localHost: d.localHost,
        localPort: d.localPort
      }
    })
  }

  out.sort((a, b) => String(a.deviceId).localeCompare(String(b.deviceId)))
  return out
}

async function refresh(manual = false) {
  if (refreshing) return
  refreshing = true
  if (manual) loading.value = true
  try {
    const [canRes, serialRes, netRes, sessRes] = await Promise.all([
      listCanChannels(),
      listSerialOpened(),
      listNetOpened(),
      listDeviceSessions(),
      loadParsers()
    ])
    rows.value = buildRows(canRes.data || [], serialRes.data || [], netRes.data || [], sessRes.data || [])
  } finally {
    refreshing = false
    if (manual) loading.value = false
  }
}

function clearLocalActive(row) {
  if (row.kind === 'can' && localStorage.getItem(ACTIVE_KEY) === row.deviceId) {
    localStorage.removeItem(ACTIVE_KEY)
  }
  if (row.kind === 'serial' && localStorage.getItem(SERIAL_ACTIVE_KEY) === row.deviceId) {
    localStorage.removeItem(SERIAL_ACTIVE_KEY)
  }
  if (row.kind === 'udp' && localStorage.getItem(UDP_ACTIVE_KEY) === row.deviceId) {
    localStorage.removeItem(UDP_ACTIVE_KEY)
  }
}

async function handleClose(row) {
  try {
    await ElMessageBox.confirm(`确认关闭 ${row.kindLabel}「${row.deviceId}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  row.closing = true
  try {
    if (row.kind === 'can') await closeCanChannel(row.closeArgs)
    else if (row.kind === 'serial') await closeSerialPort(row.closeArgs.port)
    else if (row.kind === 'udp') await closeNet(row.closeArgs)
    clearLocalActive(row)
    ElMessage.success('连接已关闭')
    await refresh(false)
  } finally {
    row.closing = false
  }
}

async function openBindParser(row) {
  if (!row) return
  await loadParsers()
  bindForm.deviceId = row.deviceId
  bindForm.kind = row.kind
  bindForm.kindLabel = row.kindLabel
  bindForm.detail = row.detail || ''
  bindForm.parserId = row.parserId || ''
  dlg.bind = true
}

async function submitBindParser() {
  if (!bindForm.deviceId || bindSaving.value) return
  bindSaving.value = true
  try {
    await bindDeviceParser({
      srcParam: bindForm.deviceId,
      srcKind: bindForm.kind,
      parserId: bindForm.parserId || ''
    })
    ElMessage.success(bindForm.parserId ? `已绑定 ${parserLabel(bindForm.parserId)}` : '已解绑解释器')
    dlg.bind = false
    await refresh(false)
  } finally {
    bindSaving.value = false
  }
}

watch(autoRefresh, v => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (v) timer = setInterval(() => refresh(false), 3000)
})

onMounted(async () => {
  await refresh(true)
  if (autoRefresh.value) timer = setInterval(() => refresh(false), 3000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.hint {
  margin-bottom: 14px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.muted {
  color: var(--el-text-color-placeholder);
}
.create-card {
  margin-top: 16px;
}
.create-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.port-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.field-tip {
  width: 100%;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}
.bind-detail {
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.conn-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}
.conn-ctrl {
  width: 240px !important;
}
.conn-ctrl--gap {
  margin-left: 8px;
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
</style>
