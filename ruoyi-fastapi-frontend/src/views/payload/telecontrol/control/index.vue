<template>
  <div class="app-container control-page">
    <el-card shadow="never">
      <template #header><span>定时遥测</span></template>
      <el-form label-width="140px">
        <el-form-item label="目标 CAN">
          <el-select v-model="activeDeviceId" clearable placeholder="请先在首页打开 CAN" style="width: 320px" @change="onCanChange">
            <el-option v-for="d in canDevices" :key="d.deviceId" :label="d.label" :value="d.deviceId" />
          </el-select>
          <el-button style="margin-left: 8px" plain :loading="canRefreshing" @click="refreshCanDevices">刷新</el-button>
        </el-form-item>
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
import { listCanChannels, getDeviceStatus } from '@/api/payload/device'
import { telecontrolControlOp } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import { getTelemetryTable } from '@/api/payload/telemetry'

const ACTIVE_KEY = 'payload:activeDeviceId'

const activeDeviceId = ref(localStorage.getItem(ACTIVE_KEY) || '')
const canDevices = ref([])
const canRefreshing = ref(false)
const timedYc = reactive({ dataCode: 'F9', intervalMs: 1000 })
const tmTypes = ['F9', 'F7', 'FF', 'FD', 'FB']
const rateDuration = ref(600)
const rateInfo = reactive({ time: '00:00:00', speed: '0', err: '0' })
const ppsOffset = ref(0)
const ppsUtc = ref('')
let statusTimer = null

function onCanChange(id) {
  if (id) localStorage.setItem(ACTIVE_KEY, id)
  else localStorage.removeItem(ACTIVE_KEY)
}

async function refreshCanDevices() {
  canRefreshing.value = true
  try {
    const res = await listCanChannels()
    const list = (res.data || [])
      .filter(c => c.alive && !c.demo)
      .map(c => ({
        ...c,
        label: `${c.deviceId}（卡${c.devIndex}/通道${c.canIndex}）`
      }))
    canDevices.value = list
    if (activeDeviceId.value && !list.some(c => c.deviceId === activeDeviceId.value)) {
      activeDeviceId.value = ''
      localStorage.removeItem(ACTIVE_KEY)
    }
    if (!activeDeviceId.value && list.length === 1) {
      activeDeviceId.value = list[0].deviceId
      localStorage.setItem(ACTIVE_KEY, activeDeviceId.value)
    }
  } finally {
    canRefreshing.value = false
  }
}

async function op(name, params = {}) {
  if (!activeDeviceId.value) return ElMessage.warning('请先选择已打开的 CAN 通道（首页新建连接）')
  try {
    const res = await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
    notifyPayloadSendResult(res, { deviceId: activeDeviceId.value, channel: 'CAN' })
  } catch { /* interceptor */ }
}

async function pollStatus() {
  if (!activeDeviceId.value) return
  try {
    const st = await getDeviceStatus(activeDeviceId.value)
    if (!st.data?.connected) {
      activeDeviceId.value = ''
      localStorage.removeItem(ACTIVE_KEY)
      await refreshCanDevices()
      ElMessage.warning('CAN 连接已断开')
      return
    }
    try {
      const tm = await getTelemetryTable('FF')
      const rows = tm.data?.rows || []
      const find = id => rows.find(r => r.id === id)?.show || '0'
      rateInfo.time = find('JGB132')
      rateInfo.speed = find('JGB133')
      rateInfo.err = find('JGB135')
    } catch { /* ignore */ }
  } catch { /* ignore */ }
}

onMounted(async () => {
  await refreshCanDevices()
  pollStatus()
  statusTimer = setInterval(() => {
    refreshCanDevices()
    pollStatus()
  }, 2000)
})
onUnmounted(() => clearInterval(statusTimer))
</script>
