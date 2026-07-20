<template>
  <div class="io-log-panel">
    <div class="io-toolbar">
      <div class="io-toolbar-left">
        <span class="io-toolbar-label">接收设置</span>
        <el-checkbox v-model="hexMode" :disabled="hexOnly">HEX 显示</el-checkbox>
        <el-button size="small" @click="clearLocal">清理</el-button>
      </div>
    </div>
    <el-input
      ref="areaRef"
      type="textarea"
      :model-value="displayText"
      readonly
      resize="none"
      class="io-area"
      placeholder="接收/发送数据将显示在这里"
    />
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

const hexMode = ref(true)
/** @type {import('vue').Ref<Array<{ seq?: number, _block: string }>>} */
const entries = ref([])
const lastSeq = ref(0)
const areaRef = ref(null)
let pollTimer = null

const displayText = computed(() => entries.value.map(e => e._block).join(''))

watch(
  () => props.deviceId,
  async (id, prev) => {
    if (id === prev) return
    // 断开：保留已显示消息，停止拉取新设备
    if (!id) return
    // 从空 → 有设备（重连）：保留消息，继续从 lastSeq 拉取增量
    // 从一个设备切到另一设备：清空后重新拉取
    if (prev) {
      entries.value = []
      lastSeq.value = 0
    }
    await pullOnce()
  }
)

function scrollToBottom() {
  const ta = areaRef.value?.textarea || areaRef.value?.$el?.querySelector('textarea')
  if (ta) ta.scrollTop = ta.scrollHeight
}

function isSend(entry) {
  return String(entry.dir || '').toLowerCase() === 'send'
}

/** 冻结单条显示格式：RECV 用当前勾选（hexOnly 时固定 HEX）；SEND 用发送时类型 */
function freezeBlock(item) {
  let displayHex
  if (props.hexOnly) {
    displayHex = true
  } else if (isSend(item)) {
    displayHex = item.displayHex != null ? !!item.displayHex : true
  } else {
    displayHex = hexMode.value
  }
  return formatIoLogBlock(item, { hexMode: displayHex, style: props.logStyle })
}

function ingest(item) {
  if (!item) return
  if (item.seq != null) {
    if (item.seq <= lastSeq.value && entries.value.some(e => e.seq === item.seq)) return
    if (item.seq > lastSeq.value) lastSeq.value = item.seq
  }
  entries.value.push({ ...item, _block: freezeBlock(item) })
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
  min-height: 280px;
}
.io-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  min-height: 28px;
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
.io-area {
  flex: 1;
}
.io-area :deep(textarea) {
  height: 100% !important;
  min-height: 260px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre;
}
</style>
