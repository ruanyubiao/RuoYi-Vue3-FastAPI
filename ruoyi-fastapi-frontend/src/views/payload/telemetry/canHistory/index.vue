<template>
  <div class="app-container replay-page">
    <el-form :inline="true" class="file-toolbar" @submit.prevent>
      <el-form-item label="遥测表">
        <TelemetryPageSelect
          v-model="tmSelect"
          :pages="tmPages"
          auto-select-first
          style="width: 280px"
          @change="onTypeChange"
        />
      </el-form-item>
      <el-form-item label="起始时间">
        <el-date-picker
          v-model="queryStartAt"
          type="datetime"
          placeholder="选择起始时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          format="YYYY-MM-DD HH:mm:ss"
          :clearable="false"
          style="width: 220px"
        />
      </el-form-item>
      <el-form-item label="结束时间">
        <el-date-picker
          v-model="queryEndAt"
          type="datetime"
          placeholder="选择结束时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          format="YYYY-MM-DD HH:mm:ss"
          :clearable="false"
          style="width: 220px"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="parsing" :disabled="!tmSelect" @click="onParse">解析</el-button>
      </el-form-item>
    </el-form>
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
        level="t1"
        hide-title
        source-kind="db"
        :poll-ms="0"
        :enable-curve-nav="false"
        v-model:type="tmSelect"
        :types="tableTypes"
        :external-snap="externalSnap"
      />
    </div>
  </div>
</template>

<script setup name="TelemetryCanHistory">
/**
 * 历史 CAN 数据：时间窗开会话后按帧取 MySQL 归档。
 * 表下拉只改 type，点「解析」才开会话/取帧。
 * PayloadTelemetryTable source-kind=db：选表不打实时 table/batch。
 */
import { ElMessage } from 'element-plus'
import PayloadTelemetryTable from '@/components/Payload/PayloadTelemetryTable.vue'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'
import TelemetryReplayBar from '@/components/Payload/TelemetryReplayBar.vue'
import { getTelemetryHistoryFrame, openTelemetryHistoryFrames } from '@/api/payload/telemetry'
import { loadTelemetryPagesCached } from '@/utils/telemetryPagesCache'

const tmSelect = ref('')
const tmPages = ref([])
const queryStartAt = ref('')
const queryEndAt = ref('')
const parsing = ref(false)
const session = ref('')
const frameIndex = ref(1)
const frameCount = ref(0)
const playing = ref(false)
const intervalMs = ref(1000)
const externalSnap = ref(null)
const frameCache = new Map()
let playTimer = null

const tableTypes = computed(() => (tmSelect.value ? [{ id: tmSelect.value, name: tmSelect.value }] : []))

function formatDateTimeSec(ms) {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function initDefaultTimeRange() {
  const end = Date.now()
  const start = end - 10 * 60 * 1000
  queryStartAt.value = formatDateTimeSec(start)
  queryEndAt.value = formatDateTimeSec(end)
}

function onTypeChange() {
  session.value = ''
  frameCache.clear()
  frameCount.value = 0
  frameIndex.value = 1
  externalSnap.value = null
  playing.value = false
}

async function onParse() {
  if (!tmSelect.value) {
    ElMessage.warning('请选择遥测表')
    return
  }
  parsing.value = true
  playing.value = false
  frameCache.clear()
  try {
    const res = await openTelemetryHistoryFrames({
      type: tmSelect.value,
      start: queryStartAt.value,
      end: queryEndAt.value
    })
    const data = res.data || {}
    session.value = data.session || ''
    frameCount.value = Number(data.frameCount) || 0
    frameIndex.value = 1
    if (frameCount.value) await loadFrame(1)
    else ElMessage.info('该时间范围内无数据')
  } catch (e) {
    ElMessage.error(e?.message || '解析失败')
  } finally {
    parsing.value = false
  }
}

function applySnap(frame) {
  if (!frame) {
    externalSnap.value = { type: tmSelect.value, rows: [], ts: '', dataSource: 'mysql' }
    return
  }
  externalSnap.value = {
    type: frame.type || tmSelect.value,
    rows: frame.rows || [],
    ts: frame.ts || '',
    dataSource: frame.dataSource || 'mysql',
    name: frame.name || ''
  }
}

async function onFrameChange(n) {
  await loadFrame(n)
}

async function loadFrame(n) {
  const idx = Number(n) || 1
  if (frameCache.has(idx)) {
    applySnap(frameCache.get(idx))
    return
  }
  if (!session.value) return
  try {
    const res = await getTelemetryHistoryFrame({ session: session.value, index: idx })
    const data = res.data || {}
    if (data.frameCount) frameCount.value = Number(data.frameCount) || frameCount.value
    if (data.frame) {
      frameCache.set(idx, data.frame)
      applySnap(data.frame)
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
  const ms = Math.max(100, Number(intervalMs.value) || 1000)
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
  intervalMs.value = Math.max(100, Number(intervalMs.value) || 1000)
  if (playing.value) startPlayTimer()
})

onMounted(async () => {
  tmPages.value = await loadTelemetryPagesCached()
  if (!tmSelect.value && tmPages.value.length) tmSelect.value = tmPages.value[0].key
  initDefaultTimeRange()
})

onDeactivated(() => {
  playing.value = false
  stopPlayTimer()
})

onUnmounted(() => {
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
.file-toolbar {
  flex-shrink: 0;
  margin-bottom: 0;
}
.file-toolbar :deep(.el-form-item) {
  margin-bottom: 8px;
  margin-right: 12px;
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
