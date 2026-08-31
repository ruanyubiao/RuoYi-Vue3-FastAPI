<template>
  <div class="app-container replay-page">
    <TelemetryFileToolbar
      v-model:file-path="filePath"
      v-model:tm-type="tmType"
      :parsing="parsing"
      @parse="onParse"
    />
    <TelemetryReplayBar
      v-model:frame-index="frameIndex"
      v-model:playing="playing"
      v-model:interval-ms="intervalMs"
      :frame-count="frameCount"
      @change="onFrameChange"
    />
    <div class="table-wrap">
      <PayloadTelemetryTable
        v-if="tableTypes.length"
        ref="tableRef"
        level="t1"
        hide-title
        source-kind="file"
        :poll-ms="0"
        :enable-curve-nav="false"
        v-model:type="tmType"
        :types="tableTypes"
        :external-snap="externalSnap"
      />
    </div>
  </div>
</template>

<script setup name="Filehistory">
/** 历史文件数据：选表+文件，点解析后用回放条按帧展示。source-kind=file，不写/不读实时遥测。
 * 组件名 Filehistory 对齐后端路由 name=path.capitalize()，才能进 keep-alive。
 */
import { ElMessage } from 'element-plus'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import TelemetryFileToolbar from '@/components/Payload/TelemetryFileToolbar.vue'
import TelemetryReplayBar from '@/components/Payload/TelemetryReplayBar.vue'
import { getTelemetryFileFrame, startFileParsePoll } from '@/api/payload/telemetry'
import cache from '@/plugins/cache'
import { fileFrameDataTs } from '@/utils/recvFileTime'

const PREFS_KEY = 'payload:fileHistory:prefs:v1'
const PARSE_TIMEOUT_MS = 60000
const INTERVAL_MIN_MS = 100

function writePrefs() {
  cache.local.setJSON(PREFS_KEY, {
    tmType: tmType.value || '',
    filePath: filePath.value || '',
    intervalMs: Number(intervalMs.value) || 1000
  })
}

const prefs = cache.local.getJSON(PREFS_KEY, {}) || {}

const filePath = ref(String(prefs.filePath || ''))
const tmType = ref(String(prefs.tmType || ''))
const parsing = ref(false)
const frameIndex = ref(1)
const frameCount = ref(0)
const playing = ref(false)
const intervalMs = ref(Math.max(INTERVAL_MIN_MS, Number(prefs.intervalMs) || 1000))
const tableRef = ref(null)
const externalSnap = ref(null)
const frameCache = new Map()
let playTimer = null
let parseJob = null

const tableTypes = computed(() => (tmType.value ? [{ id: tmType.value, name: tmType.value }] : []))

function clearCache() {
  frameCache.clear()
  externalSnap.value = null
}

watch(filePath, () => {
  clearCache()
  frameCount.value = 0
  frameIndex.value = 1
  playing.value = false
})

async function onParse() {
  if (!filePath.value || !tmType.value) {
    ElMessage.warning('请选择遥测表和文件')
    return
  }
  parsing.value = true
  playing.value = false
  clearCache()
  parseJob?.stop()
  const job = startFileParsePoll({
    type: tmType.value,
    path: filePath.value,
    timeoutMs: PARSE_TIMEOUT_MS
  })
  parseJob = job
  try {
    const data = await job.promise
    frameCount.value = Number(data.frameCount) || 0
    frameIndex.value = 1
    if (data.frame) {
      frameCache.set(1, data.frame)
      applySnap(data.frame, 1)
    }
    ElMessage.success(`已解析，共 ${frameCount.value} 帧${data.frameCountExact ? '' : '（预估）'}`)
  } catch (e) {
    if (e?.message !== '已取消解析') ElMessage.error(e?.message || '解析失败')
  } finally {
    if (parseJob === job) parseJob = null
    parsing.value = false
  }
}

function applySnap(frame, index = frameIndex.value) {
  const dataTs = frame?.ts || fileFrameDataTs(filePath.value, index) || ''
  if (!frame) {
    externalSnap.value = { type: tmType.value, rows: [], ts: dataTs, dataSource: filePath.value }
    return
  }
  externalSnap.value = {
    type: frame.type || tmType.value,
    rows: frame.rows || [],
    ts: dataTs,
    dataSource: frame.dataSource || filePath.value,
    name: frame.name || ''
  }
}

async function onFrameChange(n) {
  await loadFrame(n)
}

async function loadFrame(n) {
  const idx = Number(n) || 1
  if (frameCache.has(idx)) {
    applySnap(frameCache.get(idx), idx)
    return
  }
  if (!filePath.value) return
  try {
    const res = await getTelemetryFileFrame({ path: filePath.value, index: idx })
    const data = res.data || {}
    if (data.frameCount) frameCount.value = Number(data.frameCount) || frameCount.value // 预估改精确时更新滑块
    if (data.frame) {
      frameCache.set(idx, data.frame)
      applySnap(data.frame, idx)
    } else {
      ElMessage.warning('该帧尚未解析完成，请稍后重试')
    }
  } catch (e) {
    ElMessage.error(e?.message || '取帧失败')
  }
}

function stopPlayTimer() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function startPlayTimer() {
  stopPlayTimer()
  if (!playing.value) return
  const max = Number(frameCount.value) || 0
  if (!max || frameIndex.value >= max) {
    playing.value = false
    return
  }
  const ms = Math.max(INTERVAL_MIN_MS, Number(intervalMs.value) || 1000)
  playTimer = setInterval(() => {
    const cap = Number(frameCount.value) || 0
    if (!cap) return
    const next = frameIndex.value + 1
    if (next > cap) {
      playing.value = false
      return
    }
    frameIndex.value = next
    loadFrame(next)
    if (next >= cap) playing.value = false
  }, ms)
}

watch(playing, on => {
  if (!on) {
    stopPlayTimer()
    return
  }
  startPlayTimer()
})

watch(intervalMs, () => {
  intervalMs.value = Math.max(INTERVAL_MIN_MS, Number(intervalMs.value) || 1000)
  writePrefs()
  if (playing.value) startPlayTimer()
})

watch([tmType, filePath], writePrefs)

onDeactivated(() => {
  playing.value = false
  stopPlayTimer()
})

onUnmounted(() => {
  parseJob?.stop()
  stopPlayTimer()
})
</script>

<style scoped>
.replay-page {
  height: 100%;
  max-height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px 16px !important;
}
.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.table-wrap :deep(.payload-tm-table) {
  height: 100%;
}
</style>
