<template>
  <div class="board-connect-bar">
    <el-form :inline="true" class="left-toolbar" size="small">
      <el-form-item>
        <el-button
          v-if="!connected"
          type="primary"
          size="small"
          @click="openConnectDialog"
        >{{ isUdp ? '新建 UDP 连接' : '新建串口连接' }}</el-button>
        <el-button
          v-else
          type="success"
          plain
          size="small"
          class="btn-connected"
          @click="closeLink"
        >{{ closeButtonText }}</el-button>
      </el-form-item>
    </el-form>

    <SerialConnectDialog
      v-if="!isUdp"
      v-model="serialDlg.visible"
      :source="source"
      mode="preset"
      :preset="SERIAL_PRESET"
      :baud-choices="serialBaudChoices"
      :preferred-port="serialPort"
      :fallback-parsers="fallbackParsers"
      :fallback-assemblers="FALLBACK_ASSEMBLER_PASSTHROUGH"
      @success="onSerialSuccess"
    />
    <UdpConnectDialog
      v-else
      v-model="udpDlg.visible"
      :title="'新建 UDP 连接'"
      :source="source"
      :prefs-key="udpPrefsKey"
      :preset="UDP_PRESET"
      :show-binding-tips="false"
      @success="onUdpSuccess"
    />
  </div>
</template>

<script setup name="PayloadBoardConnectBar">
/**
 * 单板连接区：串口 / UDP 新建、关闭、断线轮询、会话恢复。
 * 通过 v-model:connected / v-model:deviceId 把链路状态交给页面。
 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { closeNet, closeSerialPort, getDeviceSnapshot } from '@/api/payload/device'
import SerialConnectDialog from '@/components/Payload/SerialConnectDialog.vue'
import UdpConnectDialog from '@/components/Payload/UdpConnectDialog.vue'
import { prefetchDeviceSnapshot } from '@/utils/deviceSnapshotCache'
import cache from '@/plugins/cache'
import { useLinkStatusPoll } from '@/utils/useLinkStatusPoll'
import {
  getDeviceConnectEntry,
  toBaudChoices,
  toSerialPreset,
  toUdpPreset
} from '@/utils/deviceConnectDefaults'
import { FALLBACK_ASSEMBLER_PASSTHROUGH } from '@/utils/pipelineIds'

const props = defineProps({
  /** serial | udp */
  kind: { type: String, default: 'serial' },
  /** 会话 source / cfg_device_connect key */
  source: { type: String, required: true },
  prefsKey: { type: String, required: true },
  udpPrefsKey: { type: String, default: '' },
  serialFallback: { type: Object, default: () => ({}) },
  udpFallback: { type: Object, default: () => ({}) },
  fallbackParsers: { type: Array, default: () => [] },
  connected: { type: Boolean, default: false },
  deviceId: { type: String, default: '' }
})

const emit = defineEmits(['update:connected', 'update:deviceId'])

const isUdp = computed(() => String(props.kind || '').toLowerCase() === 'udp')

const boardConnectCfg = ref({ ...props.serialFallback })
const SERIAL_PRESET = computed(() => toSerialPreset(boardConnectCfg.value))
const serialBaudChoices = computed(() => toBaudChoices(boardConnectCfg.value))
const UDP_PRESET = computed(() => toUdpPreset(boardConnectCfg.value))

const serialPort = ref('')
const udpLocalHost = ref('')
const udpLocalPort = ref(0)
const serialDlg = reactive({ visible: false })
const udpDlg = reactive({ visible: false })

let closingLink = false

const derivedDeviceId = computed(() => {
  if (isUdp.value) {
    if (!udpLocalHost.value || !udpLocalPort.value) return ''
    return `udp:${udpLocalHost.value}:${udpLocalPort.value}`
  }
  return serialPort.value ? `serial:${serialPort.value}` : ''
})

const closeButtonText = computed(() => {
  if (isUdp.value) {
    const host = udpLocalHost.value || '?'
    const port = udpLocalPort.value || '?'
    return `关闭 UDP · ${host}:${port}`
  }
  return `关闭串口 · ${serialPort.value}`
})

watch(
  derivedDeviceId,
  (id) => {
    if (id !== props.deviceId) emit('update:deviceId', id)
  },
  { immediate: true }
)

function setConnected(on) {
  const v = !!on
  if (v !== props.connected) emit('update:connected', v)
}

function mergePrefs(patch) {
  const cur = cache.local.getJSON(props.prefsKey, {}) || {}
  cache.local.setJSON(props.prefsKey, { ...cur, ...patch })
}

function savePrefs() {
  mergePrefs({
    serialPort: serialPort.value,
    udpLocalHost: udpLocalHost.value,
    udpLocalPort: udpLocalPort.value
  })
}

function loadPrefs() {
  const p = cache.local.getJSON(props.prefsKey, {}) || {}
  if (p.serialPort) serialPort.value = p.serialPort
  if (p.udpLocalHost) udpLocalHost.value = p.udpLocalHost
  if (p.udpLocalPort) udpLocalPort.value = Number(p.udpLocalPort) || 0
}

function openConnectDialog() {
  if (isUdp.value) udpDlg.visible = true
  else serialDlg.visible = true
}

function onSerialSuccess({ port }) {
  serialPort.value = port
  setConnected(true)
  savePrefs()
}

function onUdpSuccess({ localHost, localPort, deviceId: id }) {
  let host = localHost
  let port = localPort
  if ((!host || !port) && id) {
    const parts = String(id).split(':')
    if (parts[0] === 'udp' && parts.length >= 3) {
      host = parts.slice(1, -1).join(':')
      port = Number(parts[parts.length - 1])
    }
  }
  udpLocalHost.value = String(host || '')
  udpLocalPort.value = Number(port) || 0
  setConnected(true)
  savePrefs()
}

async function closeLink() {
  if (isUdp.value) await closeUdp()
  else await closeSerial()
}

async function closeSerial() {
  if (!serialPort.value) return
  try {
    await ElMessageBox.confirm(`确认关闭串口「${serialPort.value}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  closingLink = true
  try {
    await closeSerialPort(serialPort.value)
  } catch (e) {
    ElMessage.error(e?.message || '关闭串口失败')
    closingLink = false
    return
  }
  setConnected(false)
  closingLink = false
  savePrefs()
  ElMessage.success('串口已关闭')
}

async function closeUdp() {
  if (!udpLocalHost.value || !udpLocalPort.value) return
  const label = `${udpLocalHost.value}:${udpLocalPort.value}`
  try {
    await ElMessageBox.confirm(`确认关闭 UDP「${label}」？`, '关闭连接', {
      type: 'warning',
      confirmButtonText: '关闭',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  closingLink = true
  try {
    await closeNet({ proto: 'udp', localHost: udpLocalHost.value, localPort: udpLocalPort.value })
  } catch (e) {
    ElMessage.error(e?.message || '关闭 UDP 失败')
    closingLink = false
    return
  }
  setConnected(false)
  closingLink = false
  savePrefs()
  ElMessage.success('UDP 已关闭')
}

async function checkLinkStatus() {
  if (!props.connected || closingLink) return
  try {
    if (isUdp.value) {
      if (!udpLocalHost.value || !udpLocalPort.value) return
      const res = await getDeviceSnapshot(['netOpened'])
      const opened = res.data?.netOpened || []
      const want = `udp:${udpLocalHost.value}:${udpLocalPort.value}`
      const alive = opened.some(n => n && n.alive !== false && String(n.deviceId) === want)
      if (!alive) {
        setConnected(false)
        ElMessage.warning(`UDP 已断开（${udpLocalHost.value}:${udpLocalPort.value}）`)
      }
      return
    }
    if (!serialPort.value) return
    const res = await getDeviceSnapshot(['serialOpened'])
    const opened = res.data?.serialOpened || []
    const alive = new Set(
      opened.filter(p => p && p.alive !== false).map(p => String(p.port || '').toUpperCase())
    )
    if (!alive.has(String(serialPort.value).toUpperCase())) {
      setConnected(false)
      ElMessage.warning(`串口已断开（${serialPort.value}）`)
    }
  } catch {
    /* ignore */
  }
}

const { start: startLinkPoll } = useLinkStatusPoll(checkLinkStatus)

async function applyConnectCfg() {
  const entry = await getDeviceConnectEntry(props.source)
  if (isUdp.value) {
    boardConnectCfg.value = entry ? { ...props.udpFallback, ...entry } : { ...props.udpFallback }
  } else {
    boardConnectCfg.value = entry
      ? { ...props.serialFallback, ...entry }
      : { ...props.serialFallback }
  }
}

async function restoreBoardLink() {
  try {
    const want = props.source
    if (isUdp.value) {
      const res = await getDeviceSnapshot(['netOpened', 'sessions'])
      const opened = res.data?.netOpened || []
      const alive = new Map()
      for (const n of opened) {
        if (n?.alive === false) continue
        const id = String(n.deviceId || '').trim()
        if (id) alive.set(id, n)
      }
      const sessions = res.data?.sessions || []
      for (const s of sessions) {
        const source = String(s.source || '').trim()
        const param = String(s.srcParam || '')
        if (!param.startsWith('udp:')) continue
        if (!alive.has(param)) continue
        if (source === want) {
          const n = alive.get(param)
          udpLocalHost.value = String(n.localHost || '')
          udpLocalPort.value = Number(n.localPort) || 0
          setConnected(true)
          savePrefs()
          break
        }
      }
      return
    }
    const res = await getDeviceSnapshot(['serialOpened', 'sessions'])
    const opened = res.data?.serialOpened || []
    const alive = new Map()
    for (const p of opened) {
      if (p?.alive === false) continue
      const port = String(p.port || '').trim()
      if (port) alive.set(port.toUpperCase(), port)
    }
    const sessions = res.data?.sessions || []
    for (const s of sessions) {
      const source = String(s.source || '').trim()
      const param = String(s.srcParam || '')
      if (!param.startsWith('serial:')) continue
      const port = param.slice('serial:'.length)
      if (!alive.has(port.toUpperCase())) continue
      if (source === want) {
        serialPort.value = port
        setConnected(true)
        savePrefs()
        break
      }
    }
  } catch {
    /* ignore */
  }
}

onMounted(async () => {
  loadPrefs()
  await applyConnectCfg()
  await prefetchDeviceSnapshot()
  await restoreBoardLink()
  startLinkPoll()
})

watch(
  () => [props.source, props.kind],
  () => {
    applyConnectCfg()
  }
)
</script>

<style scoped>
.board-connect-bar {
  flex-shrink: 0;
}
.left-toolbar {
  flex-shrink: 0;
  height: 32px;
  margin: 0;
  padding: 0;
  display: flex;
  align-items: center;
}
.left-toolbar :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 10px;
}
.btn-connected {
  --el-button-bg-color: var(--el-color-success-light-9);
  --el-button-border-color: var(--el-color-success);
  --el-button-text-color: var(--el-color-success);
}
</style>
