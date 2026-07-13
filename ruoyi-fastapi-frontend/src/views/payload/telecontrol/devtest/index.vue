<template>
  <div class="app-container">
    <el-card shadow="never">
      <template #header>
        <span>CAN 遥测数据</span>
      </template>
      <el-form label-width="100px" class="dev-form">
        <el-form-item label="设备ID">
          <el-select v-model="deviceId" filterable allow-create default-first-option style="width: 280px">
            <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
          </el-select>
          <el-button link type="primary" style="margin-left: 8px" @click="refreshDevices">刷新</el-button>
        </el-form-item>
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
        说明：此处模拟 CAN 库多帧组包后的完整遥测应答。发送后经校验/解析写入 Redis，可在「遥测」菜单对应表页查看。
        <br>
        「开始模拟」：每秒递增索引4~6(字节)、7-8/9-10(无符号短整型)、11-14(无符号整型)，并重算校验和后自动发送。
      </div>
    </el-card>
  </div>
</template>

<script setup name="DevTest">
import { ElMessage } from 'element-plus'
import { listCanChannels } from '@/api/payload/device'
import { injectCanYcTest } from '@/api/payload/telemetry'

const ACTIVE_KEY = 'payload:activeDeviceId'
const SAMPLE_HEX =
  '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2 05 97 00 81 00 00 00 02 11 01 C8 0C B1 42 70 00 00 3F 2D 74 BE 44 C3 61 9A 41 6E BF 80 00 00 6D C3 80 26 00 00 55 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 02 00 21 1F AA AA AA AA 00 00 00 00 00 00 30 FF 0C 00 FC 00 00 10 00 00 00 00 00 00 03 00 CC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4C'

const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
const hexText = ref('')
const manualSending = ref(false)
const lastResult = ref(null)
const simulating = ref(false)
const simSendCount = ref(0)
const simSnapshot = ref({ b4: 0, b5: 0, b6: 0 })

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

async function refreshDevices() {
  try {
    const res = await listCanChannels()
    const list = (res.data || []).map(d => d.deviceId || d).filter(Boolean)
    const active = localStorage.getItem(ACTIVE_KEY)
    const opts = [...new Set([active, deviceId.value, ...list].filter(Boolean))]
    deviceOptions.value = opts.length ? opts : ['can:0:0:0']
    if (!opts.includes(deviceId.value)) {
      deviceId.value = deviceOptions.value[0]
    }
  } catch {
    deviceOptions.value = [deviceId.value || 'can:0:0:0']
  }
}

function fillSample() {
  hexText.value = SAMPLE_HEX
}

async function sendFrame(bytes, { quiet = false } = {}) {
  if (!deviceId.value) {
    if (!quiet) ElMessage.warning('请选择设备ID')
    throw new Error('no device')
  }
  if (!quiet) manualSending.value = true
  try {
    const res = await injectCanYcTest({ deviceId: deviceId.value, hex: formatHex(bytes) })
    lastResult.value = res.data || {}
    localStorage.setItem(ACTIVE_KEY, deviceId.value)
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
  if (!deviceId.value) {
    ElMessage.warning('请选择设备ID')
    return
  }
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

onMounted(refreshDevices)
onUnmounted(stopSimulate)
</script>

<style scoped>
.dev-form {
  max-width: 960px;
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
  margin-top: 16px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.action-btn {
  min-width: 104px;
}
</style>
