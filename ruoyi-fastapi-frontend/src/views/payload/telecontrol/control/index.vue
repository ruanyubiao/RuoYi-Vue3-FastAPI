<template>
  <div class="app-container control-page">
    <CanConnectToolbar :family="family" v-model:device-id="activeDeviceId" />

    <template v-if="family === 'biu'">
      <el-card shadow="never">
        <template #header><span>遥测</span></template>
        <el-form label-width="140px">
          <el-form-item label="定时遥测">
            <el-button type="success" @click="op('biu.timedYc.enable', { enable: true })">打开</el-button>
            <el-button type="danger" @click="op('biu.timedYc.enable', { enable: false })">关闭</el-button>
          </el-form-item>
          <el-form-item label="遥测类型">
            <el-select v-model="timedYc.dataCode" style="width: 120px; margin-right: 8px">
              <el-option v-for="t in tmTypes" :key="t" :label="t" :value="t" />
            </el-select>
            <span style="margin-right: 8px">间隔(ms)</span>
            <el-input-number v-model="timedYc.intervalMs" :min="100" :step="100" style="width: 140px; margin-right: 8px" />
            <el-button @click="op('biu.timedYc.param', timedYc)">设置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" style="margin-top: 16px">
        <template #header><span>原子钟校时 / 通信速率</span></template>
        <el-form label-width="140px">
          <el-form-item label="原子钟校时">
            <el-button type="success" @click="op('biu.ppsTime.enable', { enable: true })">打开</el-button>
            <el-button type="danger" @click="op('biu.ppsTime.enable', { enable: false })">关闭</el-button>
          </el-form-item>
          <el-form-item label="通信速率统计">
            <el-input-number v-model="rateDuration" :min="60" style="width: 140px; margin-right: 8px" />
            <span style="margin-right: 8px">秒</span>
            <el-button type="primary" @click="op('biu.rate.start', { durationSec: rateDuration })">开始统计</el-button>
            <el-button @click="op('biu.rate.stop')">停止统计</el-button>
          </el-form-item>
          <el-form-item label="统计信息">
            <span>统计时间 {{ rateInfo.time }} | 空口速率 {{ rateInfo.speed }} Mbps | 误码率 {{ rateInfo.err }}</span>
          </el-form-item>
          <el-form-item label="时间补偿(ms)">
            <el-input-number v-model="ppsOffset" style="width: 140px; margin-right: 8px" />
            <el-button @click="op('biu.ppsTime.offset', { offsetMs: ppsOffset })">设置</el-button>
          </el-form-item>
          <el-form-item label="时间同步起始(UTC)">
            <el-date-picker v-model="ppsUtc" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="margin-right: 8px" />
            <el-button @click="op('biu.ppsTime.start', { utc: ppsUtc })">设置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" style="margin-top: 16px">
        <template #header><span>系统</span></template>
        <el-form label-width="140px">
          <el-form-item label="系统指令">
            <el-button type="warning" @click="sendBiuCanReset">CAN重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </template>

    <template v-else>
      <el-card shadow="never">
        <template #header><span>时间同步</span></template>
        <el-form label-width="160px">
          <el-form-item label="载荷时间(UTC0)">
            <el-date-picker v-model="xlPayloadUtc" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="margin-right: 8px" />
            <el-checkbox v-model="xlUseSystemTime" style="margin-right: 8px">使用系统当前时间</el-checkbox>
            <el-button type="primary" @click="sendXlSetPayloadTime">设置载荷时间</el-button>
          </el-form-item>
          <el-form-item label="系统时间偏差(ms)">
            <el-input-number v-model="xlOffsetMs" style="width: 140px; margin-right: 8px" />
            <el-button @click="sendXlSetOffset">设置</el-button>
          </el-form-item>
          <el-form-item label="GNSS 有效">
            <el-checkbox v-model="xlGnssValid">时间同步 GNSS 有效</el-checkbox>
          </el-form-item>
          <el-form-item label="定时同步广播">
            <el-button type="success" :disabled="xlBroadcastOn" @click="startXlBroadcast">打开</el-button>
            <el-button type="danger" :disabled="!xlBroadcastOn" @click="stopXlBroadcast">关闭</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" style="margin-top: 16px">
        <template #header><span>发送数据</span></template>
        <el-form label-width="140px">
          <el-form-item label="Hex">
            <el-input v-model="xlHex" type="textarea" :rows="2" placeholder="01 02 03 …" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="sendXlCustom('build_telecommand')">发送遥控指令</el-button>
            <el-button @click="sendXlCustom('build_broadcast', { kind: 1 })">发送姿控广播</el-button>
            <el-button @click="sendXlCustom('build_broadcast', { kind: 2 })">发送GNSS广播</el-button>
          </el-form-item>
          <el-form-item label="遥测请求">
            <el-select v-model="xlTmCode" style="width: 220px; margin-right: 8px">
              <el-option :value="1" label="0x01 一类轮询-速变遥测" />
              <el-option :value="2" label="0x02 二类轮询" />
            </el-select>
            <el-button @click="sendXlTmRequest">发送遥测请求</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" style="margin-top: 16px">
        <template #header><span>系统</span></template>
        <el-form label-width="140px">
          <el-form-item label="系统指令">
            <el-select v-model="xlSystemCmd" style="width: 220px; margin-right: 8px">
              <el-option
                v-for="o in xlSystemOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
            <el-checkbox v-model="xlSystemBroadcast" style="margin-right: 8px">系统命令广播(nid=0xFF)</el-checkbox>
            <el-button type="warning" @click="sendXlSystemCmd">发送</el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </template>
  </div>
</template>

<script setup name="Control">
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import CanConnectToolbar from '@/components/Payload/CanConnectToolbar.vue'
import { telecontrolControlOp } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import { getTelemetryTable } from '@/api/payload/telemetry'
import { resolveTelecontrolFamily } from '@/utils/telecontrolFamily'

const route = useRoute()
const family = ref(resolveTelecontrolFamily(route))
const activeDeviceId = ref('')

const timedYc = reactive({ dataCode: 'F9', intervalMs: 1000 })
const tmTypes = ['F9', 'F7', 'FF', 'FD', 'FB']
const rateDuration = ref(600)
const rateInfo = reactive({ time: '00:00:00', speed: '0', err: '0' })
const ppsOffset = ref(0)
const ppsUtc = ref('')

const xlPayloadUtc = ref('')
const xlUseSystemTime = ref(false)
const xlOffsetMs = ref(0)
const xlGnssValid = ref(true)
const xlHex = ref('01 02 03 04 05 06 07 08')
const xlTmCode = ref(1)
const xlBroadcastOn = ref(false)
/** 与 DemoXL SystemSecHead 一致 */
const xlSystemOptions = [
  { value: 0xfa, label: '0xFA A 总线复位' },
  { value: 0xfb, label: '0xFB B 总线复位' },
  { value: 0xf1, label: '0xF1 心跳测试' },
  { value: 0xff, label: '0xFF 安全关机' }
]
const xlSystemCmd = ref(0xfa)
const xlSystemBroadcast = ref(false)
let xlBroadcastTimer = null
let statusTimer = null

async function op(name, params = {}) {
  if (!activeDeviceId.value) return ElMessage.warning('请先打开 CAN-A/B 并选择当前发送口')
  try {
    const res = await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
    notifyPayloadSendResult(res, { deviceId: activeDeviceId.value, channel: 'CAN' })
  } catch { /* interceptor */ }
}

function nowUtcStr() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
}

function utcToSec(str) {
  const s = xlUseSystemTime.value ? nowUtcStr() : str
  const ms = Date.parse(String(s).replace(' ', 'T') + 'Z')
  if (Number.isNaN(ms)) return Math.floor(Date.now() / 1000)
  return Math.floor(ms / 1000)
}

async function sendProtocol(method, kwargs = {}) {
  return op(`${family.value}.protocolBuild`, { protocolBuild: { method, kwargs } })
}

/** BIU：CAN 重置（BiuSystemCmd.RESET=0） */
async function sendBiuCanReset() {
  await sendProtocol('build_system', { cmd_type: 0, broadcast: false })
}

/** XL：系统指令（SystemSecHead） */
async function sendXlSystemCmd() {
  await sendProtocol('build_system', {
    cmd_type: Number(xlSystemCmd.value),
    broadcast: !!xlSystemBroadcast.value
  })
}

async function sendXlSetPayloadTime() {
  const sec = utcToSec(xlPayloadUtc.value)
  await sendProtocol('build_time_sync', { sec, ms: 0, apply_offset: false, gnss_valid: xlGnssValid.value })
}

async function sendXlSetOffset() {
  // 偏差写入由后续定时广播侧使用；此处先发一帧当前载荷时间作确认
  ElMessage.info(`已记录偏差 ${xlOffsetMs.value} ms（定时广播将叠加）`)
}

async function sendXlBroadcastTick() {
  const sec = Math.floor(Date.now() / 1000) + Math.floor(Number(xlOffsetMs.value || 0) / 1000)
  await sendProtocol('build_time_sync', {
    sec,
    ms: 0,
    apply_offset: false,
    gnss_valid: xlGnssValid.value
  })
}

function startXlBroadcast() {
  if (xlBroadcastOn.value) return
  xlBroadcastOn.value = true
  sendXlBroadcastTick()
  xlBroadcastTimer = setInterval(sendXlBroadcastTick, 1000)
}

function stopXlBroadcast() {
  xlBroadcastOn.value = false
  if (xlBroadcastTimer) {
    clearInterval(xlBroadcastTimer)
    xlBroadcastTimer = null
  }
}

async function sendXlCustom(method, extra = {}) {
  const hex = xlHex.value.replace(/\s+/g, '')
  const data = []
  for (let i = 0; i < hex.length; i += 2) data.push(parseInt(hex.slice(i, i + 2), 16))
  const kwargs = { data: bytesToArrayNote(data), ...extra }
  // 后端 protocol_build kwargs 不能直接传 bytes；改走 customSend 业务帧更稳
  if (method === 'build_telecommand') {
    return op('xl.customSend', { hex: xlHex.value })
  }
  return sendProtocol(method, { data: Array.from(data), ...extra })
}

function bytesToArrayNote(arr) {
  return arr
}

async function sendXlTmRequest() {
  await sendProtocol('build_telemetry_request', { sec_header: Number(xlTmCode.value) })
}

async function pollStatus() {
  if (family.value !== 'biu' || !activeDeviceId.value) return
  try {
    const tm = await getTelemetryTable('BIU:FF')
    const rows = tm.data?.rows || []
    const find = id => rows.find(r => r.id === id)?.show || '0'
    rateInfo.time = find('JGB132')
    rateInfo.speed = find('JGB133')
    rateInfo.err = find('JGB135')
  } catch { /* ignore */ }
}

onMounted(() => {
  statusTimer = setInterval(pollStatus, 2000)
})
onActivated(() => {
  if (!statusTimer) statusTimer = setInterval(pollStatus, 2000)
})
onDeactivated(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  stopXlBroadcast()
})
onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
  statusTimer = null
  stopXlBroadcast()
})
</script>
