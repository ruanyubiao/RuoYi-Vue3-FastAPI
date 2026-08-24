<template>
  <div class="payload-transfer-info">
    <div class="xfer-header">
      <span class="xfer-title">{{ title }}</span>
      <div v-if="deviceOptions.length" class="xfer-sources">
        <button
          v-for="d in deviceOptions"
          :key="d.id"
          type="button"
          class="xfer-source-btn"
          :class="{ 'is-active': d.id === activeId }"
          @click="selectSource(d.id)"
        >{{ d.label }}</button>
      </div>
      <div class="xfer-actions">
        <el-button link type="primary" size="small" :disabled="!displayText" @click="copyLocal">复制</el-button>
        <el-button link type="danger" size="small" @click="clearLocal">清理</el-button>
      </div>
    </div>
    <el-scrollbar ref="scrollRef" class="xfer-scroll">
      <pre v-if="displayText" class="xfer-pre">{{ displayText }}</pre>
    </el-scrollbar>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { getDeviceIoLog, clearDeviceIoLog } from '@/api/payload/device'

const props = defineProps({
  title: { type: String, default: '传输信息' },
  devices: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  /** 轮询间隔，默认 1.5s（避免与 image 等同页请求叠打） */
  pollMs: { type: Number, default: 1500 }
})

const emit = defineEmits(['update:modelValue'])

const activeId = computed({
  get: () => props.modelValue || (props.devices[0]?.id || ''),
  set: (v) => emit('update:modelValue', v || '')
})

const deviceOptions = computed(() => (props.devices || []).filter(d => d && d.id))
const deviceIdsKey = computed(() => deviceOptions.value.map(d => d.id).join('|'))

const lines = ref([])
const lastSeq = ref(0)
const scrollRef = ref(null)
let pollTimer = null
let pulling = false

const LINE_MAX_LEN = 112

/** 展示用截断；复制用完整内容 */
const displayText = computed(() =>
  lines.value.map(line => (line.length > LINE_MAX_LEN ? `${line.slice(0, LINE_MAX_LEN)}...` : line)).join('\n')
)
const fullText = computed(() => lines.value.join('\n'))

function selectSource(id) {
  if (!id || id === activeId.value) return
  activeId.value = id
}

function formatLine(entry) {
  const ts = entry.ts || ''
  const dir = String(entry.dir || '').toLowerCase() === 'send' ? 'Send' : 'Recv'
  const hex = String(entry.hex || '').trim()
  const msg = String(entry.message || entry.msg || '').trim()
  const body = [msg, hex].filter(Boolean).join(' ')
  return `[${ts}]#${dir} ${body}`.trimEnd()
}

function scrollToBottom() {
  nextTick(() => {
    const wrap = scrollRef.value?.wrapRef
    if (wrap) wrap.scrollTop = wrap.scrollHeight
  })
}

async function pullOnce() {
  if (!activeId.value || pulling) return
  pulling = true
  try {
    const res = await getDeviceIoLog(activeId.value, lastSeq.value)
    const list = res.data?.items || []
    if (!list.length) return
    for (const item of list) {
      if (item.seq != null) {
        if (item.seq <= lastSeq.value) continue
        lastSeq.value = item.seq
      }
      lines.value.push(formatLine(item))
    }
    if (lines.value.length > 1000) lines.value = lines.value.slice(-1000)
    scrollToBottom()
  } catch {
    /* ignore */
  } finally {
    pulling = false
  }
}

async function clearLocal() {
  lines.value = []
  lastSeq.value = 0
  if (activeId.value) {
    try {
      await clearDeviceIoLog(activeId.value)
    } catch {
      /* ignore */
    }
  }
}

async function copyLocal() {
  const text = fullText.value
  if (!text) {
    ElMessage.warning('暂无内容可复制')
    return
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败')
  }
}

function startPoll() {
  stopPoll()
  if (!activeId.value) return
  const ms = Math.max(800, Number(props.pollMs) || 1500)
  pollTimer = setInterval(pullOnce, ms)
}

function stopPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

watch(deviceIdsKey, () => {
  if (!activeId.value && deviceOptions.value.length) {
    activeId.value = deviceOptions.value[0].id
  } else if (
    activeId.value &&
    deviceOptions.value.length &&
    !deviceOptions.value.some(d => d.id === activeId.value)
  ) {
    activeId.value = deviceOptions.value[0].id
  }
})

watch(
  () => activeId.value,
  async (id, prev) => {
    if (!id) {
      stopPoll()
      return
    }
    if (prev && prev !== id) {
      lines.value = []
      lastSeq.value = 0
    }
    await pullOnce()
    startPoll()
  },
  { immediate: true }
)

/** keep-alive 切页不 unmount，须停 io-log 轮询 */
onActivated(() => {
  if (activeId.value) startPoll()
})
onDeactivated(stopPoll)
onUnmounted(stopPoll)
</script>

<style scoped>
.payload-transfer-info {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  overflow: hidden;
  background: var(--el-bg-color);
}
.xfer-header {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--el-border-color);
  flex-shrink: 0;
}
.xfer-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 1.4;
}
.xfer-sources {
  display: inline-flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
}
.xfer-source-btn {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
  color: var(--el-text-color-secondary);
  font-family: inherit;
}
.xfer-source-btn:hover {
  color: var(--el-color-primary);
}
.xfer-source-btn.is-active {
  color: var(--el-color-primary);
  font-weight: 500;
  cursor: default;
}
.xfer-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: flex-end;
  gap: 4px;
  transform: translateY(3px);
}
.xfer-actions :deep(.el-button) {
  padding-bottom: 0;
  height: auto;
  line-height: 1.4;
}
.xfer-scroll {
  flex: 1;
  min-height: 0;
  height: 0;
}
.xfer-pre {
  margin: 0;
  padding: 10px 12px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
