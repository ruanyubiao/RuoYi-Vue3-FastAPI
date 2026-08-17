<template>
  <div class="app-container control-page">
    <CanConnectToolbar :family="family" v-model:device-id="activeDeviceId" />

    <el-card shadow="never">
      <template #header><span>遥测</span></template>
      <el-form label-width="140px">
        <el-form-item label="遥测类型">
          <el-select v-model="tmType" style="width: 280px; margin-right: 8px">
            <el-option v-for="t in tmTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
          <el-button type="primary" @click="sendTmRequest">发送遥测请求</el-button>
        </el-form-item>
        <el-form-item label="定时遥测">
          <el-button type="success" :disabled="timedTmOn" @click="setTimedTm(true)">打开</el-button>
          <el-button type="danger" :disabled="!timedTmOn" @click="setTimedTm(false)">关闭</el-button>
          <span v-if="timedTmOn && timedTmCanLabel" class="hint-inline">当前发送：{{ timedTmCanLabel }}</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>时间同步</span></template>
      <el-form label-width="220px">
        <el-form-item label="载荷时间(UTC0时区)">
          <el-date-picker v-model="payloadUtc" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" :disabled="useSystemTime" style="margin-right: 8px" />
          <el-checkbox v-model="useSystemTime" style="margin-right: 8px">使用系统当前时间</el-checkbox>
          <el-button type="primary" :disabled="broadcastOn" @click="sendSetPayloadTime">设置载荷时间</el-button>
          <span class="hint-inline">不受起始时间和时间偏差影响</span>
        </el-form-item>
        <el-form-item label="时间同步的起始时间(UTC0时区)">
          <el-date-picker v-model="startUtc" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="margin-right: 8px" />
          <el-button type="primary" @click="setStartTime">设置</el-button>
          <el-button type="warning" @click="resetStartTime">重置</el-button>
          <span class="offset-label">系统时间偏差</span>
          <el-input-number v-model="offsetMs" style="width: 200px; margin: 0 8px" />
          <span style="margin-right: 8px">ms</span>
          <el-button type="primary" @click="setOffset">设置</el-button>
        </el-form-item>
        <el-form-item>
          <div class="hint">{{ startHint }}</div>
        </el-form-item>
        <el-form-item label="定时同步广播">
          <el-button type="success" :disabled="broadcastOn" @click="setBroadcast(true)">打开</el-button>
          <el-button type="danger" :disabled="!broadcastOn" @click="setBroadcast(false)">关闭</el-button>
        </el-form-item>
        <el-form-item v-if="family === 'xl'">
          <el-checkbox v-model="gnssValid">时间同步 GNSS 有效</el-checkbox>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>发送数据</span></template>
      <el-form label-width="140px">
        <el-form-item label="Hex">
          <el-input v-model="hexText" type="textarea" :rows="2" placeholder="01 02 03 …" />
        </el-form-item>
        <el-form-item>
          <template v-if="family === 'biu'">
            <el-button type="primary" @click="sendCustom('build_telecommand')">发送遥控指令</el-button>
            <el-button @click="sendCustom('build_broadcast')">发送广播</el-button>
          </template>
          <template v-else>
            <el-button type="primary" @click="sendCustom('build_telecommand')">发送遥控指令</el-button>
            <el-button @click="sendCustom('build_broadcast', { kind: 1 })">发送姿控广播</el-button>
            <el-button @click="sendCustom('build_broadcast', { kind: 2 })">发送GNSS广播</el-button>
          </template>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>系统</span></template>
      <el-form label-width="140px">
        <el-form-item label="系统指令">
          <template v-if="family === 'biu'">
            <el-button type="warning" @click="sendBiuCanReset">CAN重置</el-button>
          </template>
          <template v-else>
            <el-select v-model="xlSystemCmd" style="width: 220px; margin-right: 8px">
              <el-option v-for="o in xlSystemOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <el-checkbox v-model="xlSystemBroadcast" style="margin-right: 8px">系统命令广播(nid=0xFF)</el-checkbox>
            <el-button type="warning" @click="sendXlSystemCmd">发送</el-button>
          </template>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup name="Control">
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import CanConnectToolbar from '@/components/Payload/CanConnectToolbar.vue'
import { telecontrolControlOp } from '@/api/payload/telecontrol'
import { notifyPayloadSendResult } from '@/utils/payloadSend'
import { resolveTelecontrolFamily } from '@/utils/telecontrolFamily'

const route = useRoute()
const family = computed(() => resolveTelecontrolFamily(route))
const activeDeviceId = ref('')

const biuTmTypes = [
  { value: 'FF', label: '0xFF B-1主要包' },
  { value: 'FD', label: '0xFD B-2捕跟同轴标校包' },
  { value: 'FB', label: '0xFB B-3算轨包' },
  { value: 'F9', label: '0xF9 B-4-1指向标校包' },
  { value: 'F7', label: '0xF7 B-4-2星敏遥测包' },
  { value: 'FE', label: '0xFE 算轨异步包1' },
  { value: 'FC', label: '0xFC 算轨异步包2' }
]
const xlTmTypes = [
  { value: 1, label: '0x01 一类轮询-速变遥测' },
  { value: 2, label: '0x02 二类轮询-缓变遥测' }
]
const tmTypes = computed(() => (family.value === 'xl' ? xlTmTypes : biuTmTypes))
const tmType = ref(family.value === 'xl' ? 1 : 'FF')
const timedTmOn = ref(false)
const timedTmCanLabel = ref('')

const payloadUtc = ref('')
const useSystemTime = ref(false)
const startUtc = ref('')
const offsetMs = ref(0)
const broadcastOn = ref(false)
const gnssValid = ref(true)
const applyingRemote = ref(false)
const hexText = ref('01 02 03 04 05 06 07 08')

const xlSystemOptions = [
  { value: 0xfa, label: '0xFA A 总线复位' },
  { value: 0xfb, label: '0xFB B 总线复位' },
  { value: 0xf1, label: '0xF1 心跳测试' },
  { value: 0xff, label: '0xFF 安全关机' }
]
const xlSystemCmd = ref(0xfa)
const xlSystemBroadcast = ref(false)

const startHint = computed(() =>
  family.value === 'xl'
    ? '提示：设置起始时间后会计算偏差并显示。定时广播使用「系统时间 + 偏差」。XL 时间帧为服务对时广播 (EPOCH 2015)。'
    : '提示：设置起始时间后会计算偏差并显示。定时广播使用「系统时间 + 偏差」。BIU 时间帧为服务对时广播 (EPOCH 2020)。'
)

watch(family, val => {
  tmType.value = val === 'xl' ? 1 : 'FF'
  loadTimeSyncFromBackend()
})

watch(activeDeviceId, id => {
  if (!id) {
    timedTmOn.value = false
    timedTmCanLabel.value = ''
    broadcastOn.value = false
    applyTimeSyncDefaults()
    return
  }
  loadTimeSyncFromBackend()
})

watch(gnssValid, val => {
  if (applyingRemote || family.value !== 'xl' || !activeDeviceId.value) return
  op(`${family.value}.timeSync.setGnss`, { gnssValid: !!val }, { silent: true })
})

async function op(name, params = {}, options = {}) {
  if (!activeDeviceId.value) {
    ElMessage.warning('请先打开 CAN-A/B 并选择当前发送口')
    return null
  }
  try {
    const res = await telecontrolControlOp({ op: name, deviceId: activeDeviceId.value, params })
    const data = res?.data || {}
    if (!options.silent) {
      if (options.kind === 'offset') {
        if (data.success) ElMessage.success(data.message || '已更新偏差')
        else ElMessage.error(data.message || '设置失败')
      } else {
        notifyPayloadSendResult(res, { deviceId: activeDeviceId.value, channel: 'CAN' })
      }
    }
    return data
  } catch {
    return null
  }
}

function nowUtcStr() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
}

function applyTimeSyncDefaults() {
  const now = nowUtcStr()
  payloadUtc.value = now
  startUtc.value = now
  offsetMs.value = 0
}

async function loadTimeSyncFromBackend() {
  const now = nowUtcStr()
  payloadUtc.value = now
  if (!activeDeviceId.value) {
    startUtc.value = now
    offsetMs.value = 0
    return
  }
  applyingRemote.value = true
  try {
    const data = await op(`${family.value}.timeSync.get`, {}, { silent: true })
    startUtc.value = data && data.utc ? String(data.utc) : now
    offsetMs.value = data && data.offsetMs != null ? Number(data.offsetMs) : 0
    if (data && data.timedTm != null) timedTmOn.value = !!data.timedTm
    timedTmCanLabel.value = data && data.timedTm && data.timedTmCan ? String(data.timedTmCan) : ''
    if (data && data.broadcast != null) broadcastOn.value = !!data.broadcast
    if (data && data.gnssValid != null) gnssValid.value = !!data.gnssValid
  } finally {
    applyingRemote.value = false
  }
}

function utcToSec(str, useSystem) {
  const s = useSystem ? nowUtcStr() : str
  const ms = Date.parse(String(s).replace(' ', 'T') + 'Z')
  if (Number.isNaN(ms)) return Math.floor(Date.now() / 1000)
  return Math.floor(ms / 1000)
}

function parseHexBytes(text) {
  const hex = String(text || '').replace(/\s+/g, '')
  if (!hex || hex.length % 2) {
    ElMessage.warning('请输入偶数位 HEX')
    return null
  }
  const data = []
  for (let i = 0; i < hex.length; i += 2) {
    const b = parseInt(hex.slice(i, i + 2), 16)
    if (Number.isNaN(b)) {
      ElMessage.warning('HEX 含非法字符')
      return null
    }
    data.push(b)
  }
  return data
}

async function sendProtocol(method, kwargs = {}) {
  return op(`${family.value}.protocolBuild`, { protocolBuild: { method, kwargs } })
}

async function sendTmRequest() {
  if (family.value === 'xl') {
    return sendProtocol('build_telemetry_request', { sec_header: Number(tmType.value) })
  }
  const code = parseInt(String(tmType.value).replace(/H/gi, ''), 16)
  return sendProtocol('build_telemetry_request', { data_code: code })
}

async function refreshTimedTmStatus() {
  if (!activeDeviceId.value) {
    timedTmOn.value = false
    timedTmCanLabel.value = ''
    return
  }
  const data = await op(`${family.value}.timeSync.get`, {}, { silent: true })
  if (!data) return
  if (data.timedTm != null) timedTmOn.value = !!data.timedTm
  timedTmCanLabel.value = data.timedTm && data.timedTmCan ? String(data.timedTmCan) : ''
  if (data.broadcast != null) broadcastOn.value = !!data.broadcast
}

async function setTimedTm(enable) {
  const data = await op(`${family.value}.timedTm.enable`, { enable })
  if (data?.success) {
    timedTmOn.value = !!enable
    timedTmCanLabel.value = enable && data.timedTmCan ? String(data.timedTmCan) : ''
  }
}

async function sendSetPayloadTime() {
  if (broadcastOn.value) return
  const sec = utcToSec(payloadUtc.value, useSystemTime.value)
  const kwargs = { sec, ms: 0, apply_offset: false }
  if (family.value === 'xl') kwargs.gnss_valid = gnssValid.value
  return sendProtocol('build_time_sync', kwargs)
}

async function setStartTime() {
  const data = await op(`${family.value}.timeSync.setStart`, { utc: startUtc.value }, { kind: 'offset' })
  if (data && data.offsetMs != null) offsetMs.value = Number(data.offsetMs)
}

async function resetStartTime() {
  const data = await op(`${family.value}.timeSync.resetStart`, {}, { kind: 'offset' })
  if (data && data.offsetMs != null) offsetMs.value = Number(data.offsetMs)
  else if (data?.success) offsetMs.value = 0
}

async function setOffset() {
  const data = await op(`${family.value}.timeSync.setOffset`, { offsetMs: offsetMs.value }, { kind: 'offset' })
  if (data && data.offsetMs != null) offsetMs.value = Number(data.offsetMs)
}

async function setBroadcast(enable) {
  const data = await op(`${family.value}.timeSync.broadcast`, { enable, gnssValid: gnssValid.value })
  if (data?.success) broadcastOn.value = !!enable
}

async function sendCustom(method, extra = {}) {
  const data = parseHexBytes(hexText.value)
  if (!data) return
  if (method === 'build_telecommand') {
    return op(`${family.value}.customSend`, { hex: hexText.value })
  }
  return sendProtocol(method, { data, ...extra })
}

async function sendBiuCanReset() {
  await sendProtocol('build_system', { cmd_type: 0, broadcast: false })
}

async function sendXlSystemCmd() {
  await sendProtocol('build_system', {
    cmd_type: Number(xlSystemCmd.value),
    broadcast: !!xlSystemBroadcast.value
  })
}

onMounted(() => {
  loadTimeSyncFromBackend()
})
onActivated(() => {
  loadTimeSyncFromBackend()
})

let tmStatusTimer = null
function stopTmStatusPoll() {
  if (tmStatusTimer) {
    clearInterval(tmStatusTimer)
    tmStatusTimer = null
  }
}
watch(timedTmOn, on => {
  stopTmStatusPoll()
  if (on) tmStatusTimer = setInterval(refreshTimedTmStatus, 1000)
  else timedTmCanLabel.value = ''
})
onDeactivated(() => {
  stopTmStatusPoll()
})
onUnmounted(() => {
  stopTmStatusPoll()
})
</script>

<style scoped>
.hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  max-width: 860px;
}
.hint-inline {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.offset-label {
  margin-left: 16px;
  margin-right: 8px;
}
</style>
