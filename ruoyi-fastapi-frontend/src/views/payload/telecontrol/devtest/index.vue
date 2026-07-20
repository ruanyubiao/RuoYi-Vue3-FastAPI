<template>
  <div class="app-container">
    <el-card shadow="never" class="page-card">
      <template #header><span>CAN 遥测数据 · 开发测试</span></template>
      <div class="hint page-hint">
        三块区域：HTTP 注入模拟源；UDP / 串口为<strong>已打开设备</strong>绑定解释器（与控制页会话共用）。
        绑定只影响是否解析进遥测；控制页原始收发显示不受影响。
      </div>
    </el-card>

    <!-- 1. HTTP 发送 -->
    <el-card shadow="never" class="block-card">
      <template #header><span>HTTP 发送（模拟注入）</span></template>
      <el-form label-width="110px" class="dev-form">
        <el-form-item label="CAN遥测数据">
          <el-input
            v-model="hexText"
            type="textarea"
            :rows="8"
            :disabled="simulating"
            placeholder="输入CAN遥测数据（完整复合帧 HEX，空格可选）"
            class="hex-input"
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-button
            type="primary"
            class="action-btn"
            :loading="manualSending"
            :disabled="simulating"
            @click="handleSend"
            v-hasPermi="['payload:devtest:view']"
          >
            发送
          </el-button>
          <el-button
            class="action-btn"
            :type="simulating ? 'danger' : 'success'"
            @click="toggleSimulate"
            v-hasPermi="['payload:devtest:view']"
          >
            {{ simulating ? '停止模拟' : '开始模拟' }}
          </el-button>
          <el-button :disabled="simulating" @click="fillSample">填入样例</el-button>
          <el-button :disabled="simulating" @click="hexText = ''">清空</el-button>
        </el-form-item>
        <el-form-item v-if="simulating" label="模拟状态">
          <span class="sim-status">
            索引4: <strong>{{ simSnapshot.b4 }}</strong>
            · 索引5: <strong>{{ simSnapshot.b5 }}</strong>
            · 索引6: <strong>{{ simSnapshot.b6 }}</strong>
            · 已发送 {{ simSendCount }} 次
          </span>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="lastResult"
        :title="`已写入 Redis · 类型 0x${lastResult.dataType} · ${lastResult.name || ''} · 字段 ${lastResult.fieldCount} · ${lastResult.ts}`"
        type="success"
        show-icon
        :closable="false"
        class="result-alert"
      />
      <div class="hint">
        说明：此处模拟 CAN 库多帧组包后的完整遥测应答（src=http:devtest）。发送后经校验/解析写入 Redis，可在「遥测」菜单查看。
      </div>
    </el-card>

    <!-- 2. UDP 监听绑定 -->
    <el-card shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span>UDP 监听 · 解释器绑定</span>
          <el-button size="small" text type="primary" :loading="udpRefreshing" @click="refreshUdpDevices">刷新设备</el-button>
        </div>
      </template>
      <el-form label-width="110px" class="dev-form bind-form">
        <el-form-item label="已打开 UDP">
          <el-select
            v-model="udpDeviceId"
            clearable
            placeholder="请先在控制页打开 UDP"
            style="width: 320px"
            @change="onUdpDeviceChange"
          >
            <el-option
              v-for="d in udpDevices"
              :key="d.deviceId"
              :label="formatUdpLabel(d)"
              :value="d.deviceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="udpParserId" clearable placeholder="不绑定则不解析遥测" style="width: 320px" :disabled="!udpDeviceId">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.label || p.id" :value="p.id" />
          </el-select>
          <el-button
            type="primary"
            plain
            class="bind-btn"
            :disabled="!udpDeviceId"
            :loading="udpBinding"
            @click="bindUdpParser"
            v-hasPermi="['payload:devtest:view']"
          >
            应用绑定
          </el-button>
        </el-form-item>
      </el-form>
      <div class="hint">选择控制页已打开的 UDP，绑定解释器后，该口收到的完整复合帧将按解释器解析进遥测（原始收发仍在控制页显示）。</div>
    </el-card>

    <!-- 3. 串口监听绑定 -->
    <el-card shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span>串口监听 · 解释器绑定</span>
          <el-button size="small" text type="primary" :loading="serialRefreshing" @click="refreshSerialDevices">刷新设备</el-button>
        </div>
      </template>
      <el-form label-width="110px" class="dev-form bind-form">
        <el-form-item label="已打开串口">
          <el-select
            v-model="serialDeviceId"
            clearable
            placeholder="请先在控制页打开串口"
            style="width: 320px"
            @change="onSerialDeviceChange"
          >
            <el-option
              v-for="d in serialDevices"
              :key="d.deviceId"
              :label="formatSerialLabel(d)"
              :value="d.deviceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="解释器">
          <el-select v-model="serialParserId" clearable placeholder="不绑定则不解析遥测" style="width: 320px" :disabled="!serialDeviceId">
            <el-option v-for="p in parserOptions" :key="p.id" :label="p.label || p.id" :value="p.id" />
          </el-select>
          <el-button
            type="primary"
            plain
            class="bind-btn"
            :disabled="!serialDeviceId"
            :loading="serialBinding"
            @click="bindSerialParser"
            v-hasPermi="['payload:devtest:view']"
          >
            应用绑定
          </el-button>
        </el-form-item>
      </el-form>
      <div class="hint">选择控制页已打开的串口，绑定解释器后同上。请确保对端发送的是完整遥测复合帧（与 HTTP 注入格式一致）。</div>
    </el-card>
  </div>
</template>

<script setup name="DevTest">
import { ElMessage } from 'element-plus'
import { injectCanYcTest } from '@/api/payload/telemetry'
import {
  listParsers,
  listSerialOpened,
  listNetOpened,
  getDeviceStatus,
  bindDeviceParser
} from '@/api/payload/device'

const SAMPLE_HEX =
  '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C'

const hexText = ref('')
const manualSending = ref(false)
const lastResult = ref(null)
const simulating = ref(false)
const simSendCount = ref(0)
const simSnapshot = ref({ b4: 0, b5: 0, b6: 0 })

const parserOptions = ref([])
const udpDevices = ref([])
const serialDevices = ref([])
const udpDeviceId = ref('')
const serialDeviceId = ref('')
const udpParserId = ref('')
const serialParserId = ref('')
const udpRefreshing = ref(false)
const serialRefreshing = ref(false)
const udpBinding = ref(false)
const serialBinding = ref(false)

let simTimer = null
let frameBytes = null

function parseHex(text) {
  const cleaned = (text || '').replace(/\s+/g, '')
  if (!cleaned) throw new Error('HEX 为空')
  if (cleaned.length % 2) throw new Error('HEX 长度必须为偶数')
  if (!/^[0-9a-fA-F]+$/.test(cleaned)) throw new Error('HEX 含非法字符')
  const bytes = new Uint8Array(cleaned.length / 2)
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16)
  }
  return bytes
}

function formatHex(bytes) {
  return Array.from(bytes)
    .map(b => b.toString(16).toUpperCase().padStart(2, '0'))
    .join(' ')
}

function checksumIndex(bytes) {
  if (bytes.length < 5) throw new Error('帧过短')
  const dataLen = (bytes[0] << 8) | bytes[1]
  const idx = dataLen + 2
  if (idx >= bytes.length) throw new Error(`校验和位置越界: ${idx}`)
  return idx
}

function recalcChecksum(bytes) {
  const idx = checksumIndex(bytes)
  let sum = 0
  for (let i = 0; i < idx; i++) sum += bytes[i]
  bytes[idx] = sum & 0xFF
  return bytes
}

function loadFrameFromHex(text) {
  const bytes = parseHex(text)
  checksumIndex(bytes)
  return bytes
}

function readU16BE(bytes, off) {
  return (bytes[off] << 8) | bytes[off + 1]
}

function writeU16BE(bytes, off, val) {
  bytes[off] = (val >> 8) & 0xFF
  bytes[off + 1] = val & 0xFF
}

function readU32BE(bytes, off) {
  return ((bytes[off] << 24) | (bytes[off + 1] << 16) | (bytes[off + 2] << 8) | bytes[off + 3]) >>> 0
}

function writeU32BE(bytes, off, val) {
  bytes[off] = (val >> 24) & 0xFF
  bytes[off + 1] = (val >> 16) & 0xFF
  bytes[off + 2] = (val >> 8) & 0xFF
  bytes[off + 3] = val & 0xFF
}

function incrementSimFields(bytes) {
  if (bytes.length < 15) throw new Error('帧长度不足，无法递增索引4~14')
  bytes[4] = (bytes[4] + 1) & 0xFF
  bytes[5] = (bytes[5] + 1) & 0xFF
  bytes[6] = (bytes[6] + 1) & 0xFF
  writeU16BE(bytes, 7, (readU16BE(bytes, 7) + 1) & 0xFFFF)
  writeU16BE(bytes, 9, (readU16BE(bytes, 9) + 1) & 0xFFFF)
  writeU32BE(bytes, 11, (readU32BE(bytes, 11) + 1) >>> 0)
  recalcChecksum(bytes)
  return bytes
}

function fillSample() {
  hexText.value = SAMPLE_HEX
}

async function sendFrame(bytes, { quiet = false } = {}) {
  if (!quiet) manualSending.value = true
  try {
    const res = await injectCanYcTest({ hex: formatHex(bytes) })
    lastResult.value = res.data || {}
    if (!quiet) ElMessage.success(res.msg || '注入成功')
    return res
  } finally {
    if (!quiet) manualSending.value = false
  }
}

async function handleSend() {
  if (!hexText.value.trim()) {
    ElMessage.warning('请输入 CAN 遥测数据')
    return
  }
  try {
    const bytes = loadFrameFromHex(hexText.value)
    recalcChecksum(bytes)
    hexText.value = formatHex(bytes)
    await sendFrame(bytes)
  } catch (e) {
    ElMessage.error(e.message || '发送失败')
  }
}

function syncSimSnapshot(bytes) {
  simSnapshot.value = { b4: bytes[4], b5: bytes[5], b6: bytes[6] }
}

async function simTick() {
  if (!frameBytes) return
  try {
    incrementSimFields(frameBytes)
    syncSimSnapshot(frameBytes)
    hexText.value = formatHex(frameBytes)
    simSendCount.value += 1
    await sendFrame(frameBytes, { quiet: true })
  } catch (e) {
    stopSimulate()
    ElMessage.error(e.message || '模拟发送失败')
  }
}

function startSimulate() {
  try {
    if (!hexText.value.trim()) hexText.value = SAMPLE_HEX
    frameBytes = loadFrameFromHex(hexText.value)
    recalcChecksum(frameBytes)
    syncSimSnapshot(frameBytes)
    hexText.value = formatHex(frameBytes)
    simSendCount.value = 0
    simulating.value = true
    simTick()
    simTimer = setInterval(simTick, 1000)
  } catch (e) {
    frameBytes = null
    ElMessage.error(e.message || '无法启动模拟')
  }
}

function stopSimulate() {
  simulating.value = false
  if (simTimer) {
    clearInterval(simTimer)
    simTimer = null
  }
}

function toggleSimulate() {
  if (simulating.value) stopSimulate()
  else startSimulate()
}

function formatUdpLabel(d) {
  const host = d.localHost || '?'
  const port = d.localPort != null ? d.localPort : '?'
  return `${host}:${port}（${d.deviceId}）`
}

function formatSerialLabel(d) {
  return `${d.port || d.deviceId}（${d.deviceId}）`
}

async function loadParsers() {
  try {
    const res = await listParsers()
    const list = res.data?.parsers || res.data || []
    parserOptions.value = Array.isArray(list)
      ? list.map(p =>
          typeof p === 'string'
            ? { id: p, label: p }
            : { id: p.id || p.parserId, label: p.name || p.label || p.id || p.parserId }
        )
      : []
  } catch {
    parserOptions.value = [{ id: 'tm_can_yc', label: 'tm_can_yc' }]
  }
}

async function refreshUdpDevices() {
  udpRefreshing.value = true
  try {
    const res = await listNetOpened()
    udpDevices.value = (res.data || []).filter(d => d.alive !== false)
    if (udpDeviceId.value && !udpDevices.value.some(d => d.deviceId === udpDeviceId.value)) {
      udpDeviceId.value = ''
      udpParserId.value = ''
    }
  } finally {
    udpRefreshing.value = false
  }
}

async function refreshSerialDevices() {
  serialRefreshing.value = true
  try {
    const res = await listSerialOpened()
    serialDevices.value = (res.data || []).filter(d => d.alive !== false)
    if (serialDeviceId.value && !serialDevices.value.some(d => d.deviceId === serialDeviceId.value)) {
      serialDeviceId.value = ''
      serialParserId.value = ''
    }
  } finally {
    serialRefreshing.value = false
  }
}

async function loadParserForDevice(deviceId, targetRef) {
  if (!deviceId) {
    targetRef.value = ''
    return
  }
  try {
    const st = await getDeviceStatus(deviceId)
    targetRef.value = st.data?.parserId || ''
  } catch {
    targetRef.value = ''
  }
}

function onUdpDeviceChange(id) {
  loadParserForDevice(id, udpParserId)
}

function onSerialDeviceChange(id) {
  loadParserForDevice(id, serialParserId)
}

async function bindUdpParser() {
  if (!udpDeviceId.value) return
  udpBinding.value = true
  try {
    await bindDeviceParser({
      srcParam: udpDeviceId.value,
      srcKind: 'udp',
      parserId: udpParserId.value || ''
    })
    ElMessage.success(udpParserId.value ? `UDP 已绑定 ${udpParserId.value}` : 'UDP 已解绑解释器')
  } finally {
    udpBinding.value = false
  }
}

async function bindSerialParser() {
  if (!serialDeviceId.value) return
  serialBinding.value = true
  try {
    await bindDeviceParser({
      srcParam: serialDeviceId.value,
      srcKind: 'serial',
      parserId: serialParserId.value || ''
    })
    ElMessage.success(serialParserId.value ? `串口已绑定 ${serialParserId.value}` : '串口已解绑解释器')
  } finally {
    serialBinding.value = false
  }
}

onMounted(async () => {
  await loadParsers()
  await Promise.all([refreshUdpDevices(), refreshSerialDevices()])
})
onUnmounted(stopSimulate)
</script>

<style scoped>
.page-card,
.block-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.dev-form {
  max-width: 960px;
}
.bind-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
  gap: 8px;
}
.bind-btn {
  margin-left: 0;
}
.hex-input :deep(textarea) {
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
}
.result-alert {
  margin-top: 8px;
  max-width: 960px;
}
.sim-status {
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.hint {
  margin-top: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.page-hint {
  margin-top: 0;
}
.action-btn {
  min-width: 104px;
}
</style>
