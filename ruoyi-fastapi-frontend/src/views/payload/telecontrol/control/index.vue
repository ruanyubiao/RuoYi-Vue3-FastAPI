<template>
  <div class="app-container control-page">
    <el-card shadow="never">
      <template #header><span>设备连接</span></template>
      <el-form label-width="140px" class="control-form">
        <el-form-item label="CAN通道">
          <el-select v-model="canForm.canIndex" style="width: 120px; margin-right: 8px">
            <el-option v-for="ch in canOptions" :key="ch" :label="`CAN ${ch}`" :value="ch" />
          </el-select>
          <el-button type="primary" @click="handleOpenCan">打开</el-button>
          <el-button @click="handleCloseCan">关闭</el-button>
          <el-tag :type="canConnected ? 'success' : 'info'" style="margin-left: 12px">
            {{ canConnected ? '已连接' : '未连接' }} {{ activeDeviceId }}
          </el-tag>
        </el-form-item>
        <el-form-item label="串口">
          <el-select v-model="serialPort" filterable style="width: 160px; margin-right: 8px">
            <el-option v-for="p in serialPorts" :key="p.port" :label="p.port" :value="p.port" />
          </el-select>
          <el-button type="primary" @click="handleOpenSerial">打开</el-button>
          <el-button @click="handleCloseSerial">关闭</el-button>
        </el-form-item>
      </el-form>
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

<script setup name="PayloadControl">
import { listCanChannels, openCanChannel, closeCanChannel, listSerialPorts, openSerialPort, closeSerialPort, getDeviceStatus } from '@/api/payload/device'
import { telecontrolControlOp } from '@/api/payload/telecontrol'
import { getTelemetryTable } from '@/api/payload/telemetry'

const ACTIVE_KEY = 'payload:activeDeviceId'
const canOptions = [0, 1]
const canForm = reactive({ vendor: 0, devIndex: 0, canIndex: 0, baudRate: 500, nodeAddrTo: 13, cableFlag: 0 })
const activeDeviceId = ref(localStorage.getItem(ACTIVE_KEY) || '')
const canConnected = ref(false)
const serialPorts = ref([])
const serialPort = ref('')
const timedYc = reactive({ dataCode: 'F9', intervalMs: 1000 })
const tmTypes = ['F9', 'F7', 'FF', 'FD', 'FB']
const rateDuration = ref(600)
const rateInfo = reactive({ time: '00:00:00', speed: '0', err: '0' })
const ppsOffset = ref(0)
const ppsUtc = ref('')
let statusTimer = null

async function refreshSerialPorts() {
  const res = await listSerialPorts()
  serialPorts.value = res.data || []
  if (!serialPort.value && serialPorts.value.length) serialPort.value = serialPorts.value[0].port
}

async function handleOpenCan() {
  const res = await openCanChannel({ ...canForm })
  activeDeviceId.value = res.data.deviceId
  localStorage.setItem(ACTIVE_KEY, activeDeviceId.value)
  canConnected.value = true
  ElMessage.success('CAN 通道已打开')
}

async function handleCloseCan() {
  await closeCanChannel({ ...canForm })
  canConnected.value = false
  ElMessage.success('CAN 通道已关闭')
}

async function handleOpenSerial() {
  if (!serialPort.value) return
  await openSerialPort({ port: serialPort.value, mode: 'raw' })
  ElMessage.success('串口已打开')
}

async function handleCloseSerial() {
  if (!serialPort.value) return
  await closeSerialPort(serialPort.value)
  ElMessage.success('串口已关闭')
}

async function op(name, params = {}) {
  if (!activeDeviceId.value) {
    ElMessage.warning('请先打开 CAN 通道')
    return
  }
  await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
  ElMessage.success('操作已下发')
}

async function pollStatus() {
  if (!activeDeviceId.value) return
  try {
    const st = await getDeviceStatus(activeDeviceId.value)
    canConnected.value = !!st.data?.connected
    const tm = await getTelemetryTable(activeDeviceId.value, 'FF')
    const rows = tm.data?.rows || []
    const find = (id) => rows.find(r => r.id === id)?.show || '0'
    rateInfo.time = find('JGB132')
    rateInfo.speed = find('JGB133')
    rateInfo.err = find('JGB135')
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  refreshSerialPorts()
  pollStatus()
  statusTimer = setInterval(pollStatus, 2000)
})
onUnmounted(() => clearInterval(statusTimer))
</script>

<style scoped>
.control-form :deep(.el-form-item) { margin-bottom: 14px; }
</style>
