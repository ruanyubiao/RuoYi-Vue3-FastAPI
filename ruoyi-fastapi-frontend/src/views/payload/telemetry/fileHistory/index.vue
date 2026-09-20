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
import { decideFileParseAction, getTelemetryFileFrame, getTelemetryFileStatus, startFileParsePoll } from '@/api/payload/telemetry'
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
const pathHash = ref('')
let replayInvalid = false
let scanActive = false
let lastParseKey = ''

function currentParseKey() {
  return `${String(tmType.value || '').toUpperCase()}|${filePath.value || ''}`
}

const tableTypes = computed(() => (tmType.value ? [{ id: tmType.value, name: tmType.value }] : []))

function clearCache() {
  frameCache.clear()
  externalSnap.value = null
}

function resetReplayUi() {
  playing.value = false
  stopPlayTimer()
  clearCache()
  frameCount.value = 0
  frameIndex.value = 1
  pathHash.value = ''
}

function invalidateReplay(msg) {
  if (replayInvalid) return
  replayInvalid = true
  resetReplayUi()
  if (msg) ElMessage.warning(msg)
}

watch(filePath, () => {
  replayInvalid = false
  resetReplayUi()
  parseJob?.stop()
  scanActive = false
  lastParseKey = ''
})

async function applyExistingSession(data) {
  replayInvalid = false
  lastParseKey = currentParseKey()
  if (data?.pathHash) pathHash.value = data.pathHash
  frameCount.value = Number(data?.frameCount) || 0
  frameIndex.value = 1
  if (data?.frame) {
    frameCache.set(1, data.frame)
    applySnap(data.frame, 1)
  } else {
    await loadFrame(1)
  }
  ElMessage.success(`已使用现有解析，当前 ${frameCount.value} 帧`)
}

async function onParse() {
  if (!filePath.value || !tmType.value) {
    ElMessage.warning('请选择遥测表和文件')
    return
  }
  const key = currentParseKey()
  if (scanActive && lastParseKey === key) {
    ElMessage.info('正在解析中')
    return
  }
  let force = 0
  let existing = null
  try {
    const res = await getTelemetryFileStatus({ path: filePath.value, channel: 'history' })
    const action = decideFileParseAction(res.data, tmType.value)
    if (action === 'use' || action === 'confirm') {
      await applyExistingSession(res.data)
      return
    }
    existing = res.data || null
  } catch {
    // 状态查不到时按新文件直接解析
  }
  parsing.value = true
  playing.value = false
  replayInvalid = false
  clearCache()
  frameCount.value = Number(existing?.frameCount) || 0
  frameIndex.value = 1
  if (existing?.pathHash) pathHash.value = existing.pathHash
  if (existing?.frame) {
    frameCache.set(1, existing.frame)
    applySnap(existing.frame, 1)
  }
  parseJob?.stop()
  scanActive = true
  lastParseKey = key
  const job = startFileParsePoll({
    type: tmType.value,
    path: filePath.value,
    channel: 'history',
    timeoutMs: PARSE_TIMEOUT_MS,
    force,
    onProgress(data) {
      if (data.pathHash) pathHash.value = data.pathHash
      if (data.frameCount) frameCount.value = Number(data.frameCount) || frameCount.value
    }
  })
  parseJob = job
  try {
    const data = await job.promise
    if (data.pathHash) pathHash.value = data.pathHash
    frameCount.value = Number(data.frameCount) || 0
    frameIndex.value = 1
    if (data.frame) {
      frameCache.set(1, data.frame)
      applySnap(data.frame, 1)
    }
    ElMessage.success(`已解析，当前 ${frameCount.value} 帧${data.complete || data.frameCountExact ? '' : '（扫描中）'}`)
  } catch (e) {
    if (lastParseKey === key) scanActive = false
    if (e?.message !== '已取消解析') ElMessage.error(e?.message || '解析失败')
  } finally {
    parsing.value = false
  }
  job.done.finally(() => {
    if (lastParseKey === key) scanActive = false
  })
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
  if (replayInvalid) return
  const idx = Number(n) || 1
  if (frameCache.has(idx)) {
    applySnap(frameCache.get(idx), idx)
    return
  }
  if (!filePath.value) return
  try {
    const res = await getTelemetryFileFrame(
      pathHash.value
        ? { pathHash: pathHash.value, index: idx, channel: 'history' }
        : { path: filePath.value, index: idx, channel: 'history' }
    )
    if (replayInvalid) return
    const data = res.data || {}
    if (data.frame) {
      if (data.frameCount) frameCount.value = Number(data.frameCount) || frameCount.value
      frameCache.set(idx, data.frame)
      applySnap(data.frame, idx)
      return
    }
    if (data.sessionGone) {
      invalidateReplay('该文件会话已失效，请重新解析')
      return
    }
    if (!data.frame) {
      ElMessage.warning('该帧尚未解析完成')
    }
  } catch (e) {
    const msg = String(e?.message || '取帧失败')
    if (/无效|失效|未运行|过期/.test(msg)) {
      invalidateReplay(msg === 'error' ? '该文件会话已失效，请重新解析' : msg)
      return
    }
    if (!replayInvalid) ElMessage.error(msg)
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

onActivated(() => {
  if (!pathHash.value) return
  frameCache.delete(frameIndex.value)
  loadFrame(frameIndex.value)
})

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
