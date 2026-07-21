<template>
  <div class="io-log-panel">
    <div class="io-toolbar">
      <div class="io-toolbar-left">
        <span class="io-toolbar-label">接收设置</span>
        <el-checkbox v-model="hexMode" :disabled="hexOnly">HEX 显示</el-checkbox>
        <el-button size="small" @click="clearLocal">清理</el-button>
      </div>
    </div>
    <el-scrollbar ref="scrollRef" class="io-scroll">
      <pre v-if="displayText" class="io-pre">{{ displayText }}</pre>
      <div v-else class="io-placeholder">接收/发送数据将显示在这里</div>
    </el-scrollbar>
  </div>
</template>

<script setup>
import { formatIoLogBlock } from '@/utils/payloadRawData'
import { getDeviceIoLog, clearDeviceIoLog } from '@/api/payload/device'

const props = defineProps({
  /** 当前关注的设备 ID；断开为空时保留本地消息 */
  deviceId: { type: String, default: '' },
  /** default=CAN/串口；udp=消息头带 to/from peer */
  logStyle: { type: String, default: 'default' },
  /** 仅 HEX 显示（如 CAN），禁用切换 */
  hexOnly: { type: Boolean, default: false },
  pollMs: { type: Number, default: 500 }
})

const HEX_PREFS_KEY = 'payload:ioLog:hexByDevice'
/** 每条 RECV 的显示方式：{ [deviceId]: { [seq]: true|false } } */
const ENTRY_HEX_KEY = 'payload:ioLog:entryHexByDevice'
const ENTRY_HEX_MAX = 2000

const hexMode = ref(true)
/** @type {import('vue').Ref<Array<{ seq?: number, _block: string, _displayHex?: boolean }>>} */
const entries = ref([])
const lastSeq = ref(0)
const scrollRef = ref(null)
let pollTimer = null
let loadingHexPref = false

const displayText = computed(() => entries.value.map(e => e._block).join(''))

function readHexPrefs() {
  try {
    const raw = localStorage.getItem(HEX_PREFS_KEY)
    const obj = raw ? JSON.parse(raw) : {}
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

/** 按设备读取 HEX 勾选；默认 true；hexOnly 固定 true */
function loadHexForDevice(deviceId) {
  if (props.hexOnly) return true
  if (!deviceId) return true
  const prefs = readHexPrefs()
  if (Object.prototype.hasOwnProperty.call(prefs, deviceId)) return !!prefs[deviceId]
  return true
}

function saveHexForDevice(deviceId, val) {
  if (!deviceId || props.hexOnly) return
  try {
    const prefs = readHexPrefs()
    prefs[deviceId] = !!val
    localStorage.setItem(HEX_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* ignore */
  }
}

function readEntryHexAll() {
  try {
    const raw = localStorage.getItem(ENTRY_HEX_KEY)
    const obj = raw ? JSON.parse(raw) : {}
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

function getSavedEntryHex(deviceId, seq) {
  if (!deviceId || seq == null) return undefined
  const map = readEntryHexAll()[deviceId]
  if (!map || typeof map !== 'object') return undefined
  const key = String(seq)
  if (!Object.prototype.hasOwnProperty.call(map, key)) return undefined
  return !!map[key]
}

function saveEntryHex(deviceId, seq, displayHex) {
  if (!deviceId || seq == null || props.hexOnly) return
  try {
    const all = readEntryHexAll()
    const prev = all[deviceId] && typeof all[deviceId] === 'object' ? all[deviceId] : {}
    const next = { ...prev, [String(seq)]: !!displayHex }
    const keys = Object.keys(next)
    if (keys.length > ENTRY_HEX_MAX) {
      keys
        .map(Number)
        .sort((a, b) => a - b)
        .slice(0, keys.length - ENTRY_HEX_MAX)
        .forEach(k => delete next[String(k)])
    }
    all[deviceId] = next
    localStorage.setItem(ENTRY_HEX_KEY, JSON.stringify(all))
  } catch {
    /* ignore */
  }
}

function clearEntryHexForDevice(deviceId) {
  if (!deviceId) return
  try {
    const all = readEntryHexAll()
    delete all[deviceId]
    localStorage.setItem(ENTRY_HEX_KEY, JSON.stringify(all))
  } catch {
    /* ignore */
  }
}

function applyHexForDevice(deviceId) {
  loadingHexPref = true
  hexMode.value = loadHexForDevice(deviceId)
  nextTick(() => {
    loadingHexPref = false
  })
}

watch(
  () => props.hexOnly,
  v => {
    if (v) {
      loadingHexPref = true
      hexMode.value = true
      nextTick(() => {
        loadingHexPref = false
      })
    } else if (props.deviceId) {
      applyHexForDevice(props.deviceId)
    }
  },
  { immediate: true }
)

watch(hexMode, val => {
  if (loadingHexPref) return
  // 只影响之后新到的 RECV；已显示条目的方式各自冻结并已按条落盘
  saveHexForDevice(props.deviceId, val)
})

watch(
  () => props.deviceId,
  async (id, prev) => {
    if (id === prev) return
    // 断开：保留已显示消息，停止拉取新设备
    if (!id) return
    applyHexForDevice(id)
    // 从空 → 有设备（重连）：保留消息，继续从 lastSeq 拉取增量
    // 从一个设备切到另一设备：清空后重新拉取
    if (prev) {
      entries.value = []
      lastSeq.value = 0
    }
    await pullOnce()
  }
)

watch(
  () => props.logStyle,
  () => {
    if (!entries.value.length) return
    entries.value = entries.value.map(e => ({
      ...e,
      _block: freezeBlock(e, e._displayHex != null ? !!e._displayHex : resolveDisplayHex(e))
    }))
  }
)

function scrollToBottom() {
  nextTick(() => {
    const wrap = scrollRef.value?.wrapRef
    if (wrap) wrap.scrollTop = wrap.scrollHeight
  })
}

function isSend(entry) {
  return String(entry.dir || '').toLowerCase() === 'send'
}

/**
 * 解析本条应使用的显示方式：
 * - CAN hexOnly → 固定 HEX
 * - SEND → 发送时类型
 * - RECV → 条目已冻结 / 本地按 seq 保存 / 当前勾选（新消息）
 */
function resolveDisplayHex(item) {
  if (props.hexOnly) return true
  if (isSend(item)) return item.displayHex != null ? !!item.displayHex : true
  if (item._displayHex != null) return !!item._displayHex
  const saved = getSavedEntryHex(props.deviceId, item.seq)
  if (saved !== undefined) return saved
  return hexMode.value
}

function freezeBlock(item, displayHex) {
  return formatIoLogBlock(item, { hexMode: displayHex, style: props.logStyle })
}

function ingest(item) {
  if (!item) return
  if (item.seq != null) {
    if (item.seq <= lastSeq.value && entries.value.some(e => e.seq === item.seq)) return
    if (item.seq > lastSeq.value) lastSeq.value = item.seq
  }
  const displayHex = resolveDisplayHex(item)
  // 新 RECV（无历史记录）按当前勾选冻结并保存，刷新后仍按条恢复
  if (!isSend(item) && !props.hexOnly && item.seq != null && getSavedEntryHex(props.deviceId, item.seq) === undefined) {
    saveEntryHex(props.deviceId, item.seq, displayHex)
  }
  entries.value.push({ ...item, _displayHex: displayHex, _block: freezeBlock(item, displayHex) })
}

async function pullOnce() {
  if (!props.deviceId) return
  try {
    const res = await getDeviceIoLog(props.deviceId, lastSeq.value)
    const list = res.data?.items || []
    if (!list.length) return
    for (const item of list) ingest(item)
    if (entries.value.length > 2000) {
      entries.value = entries.value.slice(-1500)
    }
    nextTick(scrollToBottom)
  } catch {
    /* ignore */
  }
}

async function clearLocal() {
  entries.value = []
  lastSeq.value = 0
  clearEntryHexForDevice(props.deviceId)
  if (props.deviceId) {
    try {
      await clearDeviceIoLog(props.deviceId)
    } catch {
      /* ignore */
    }
  }
}

/** 本地立即追加（发送成功后可调用，无需等轮询） */
function appendLocal(entry) {
  ingest(entry)
  nextTick(scrollToBottom)
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(pullOnce, props.pollMs)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  if (props.deviceId) applyHexForDevice(props.deviceId)
  if (props.deviceId) pullOnce()
  startPoll()
})
onUnmounted(stopPoll)

defineExpose({ appendLocal, clearLocal, pullOnce })
</script>

<style scoped>
.io-log-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  flex: 1;
}
.io-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  min-height: 28px;
  flex-shrink: 0;
}
.io-toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.io-toolbar-label {
  font-weight: 600;
  font-size: 14px;
}
.io-scroll {
  flex: 1;
  min-height: 0;
  height: 0;
  width: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
}
.io-scroll :deep(.el-scrollbar) {
  height: 100%;
}
.io-scroll :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
}
.io-scroll :deep(.el-scrollbar__bar.is-vertical) {
  right: 0;
}
.io-pre {
  margin: 0;
  padding: 10px 12px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--el-text-color-regular);
}
.io-placeholder {
  padding: 10px 12px;
  color: var(--el-text-color-placeholder);
  font-size: 13px;
}
</style>
