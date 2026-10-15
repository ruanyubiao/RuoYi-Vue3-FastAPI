<template>
  <div class="app-container lvds-page">
    <div class="lvds-top">
      <span>采样率 {{ sampleRate }} KHz</span>
      <span>FPS {{ fps }}</span>
      <span>已选 {{ selectedSignals.length }}/8</span>
      <el-button size="small" @click="paused = !paused">{{ paused ? '继续' : '暂停' }}</el-button>
    </div>
    <el-row :gutter="12">
      <el-col :span="5">
        <el-card shadow="never">
          <template #header>
            <span>信号选择</span>
            <el-button link type="danger" @click="clearSignals">清空</el-button>
          </template>
          <el-checkbox-group v-model="selectedSignals" :max="8">
            <div v-for="s in signals" :key="s.id" class="signal-item">
              <el-checkbox :label="s.id">{{ s.name }} / {{ s.varName }}</el-checkbox>
            </div>
          </el-checkbox-group>
        </el-card>
      </el-col>
      <el-col :span="14">
        <div ref="chartRef" class="chart-box" />
      </el-col>
      <el-col :span="5">
        <el-card shadow="never" header="测量面板">
          <el-form label-width="80px" size="small">
            <el-form-item label="目标信号">
              <el-select v-model="measureSignal" style="width: 100%">
                <el-option v-for="s in selectedSignals" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
            <el-form-item label="C1 X">{{ cursor1.x }}</el-form-item>
            <el-form-item label="C1 Y">{{ cursor1.y }}</el-form-item>
            <el-form-item label="C2 X">{{ cursor2.x }}</el-form-item>
            <el-form-item label="C2 Y">{{ cursor2.y }}</el-form-item>
            <el-form-item label="ΔT">{{ deltaT }}</el-form-item>
            <el-form-item label="ΔY">{{ deltaY }}</el-form-item>
            <el-form-item label="Freq">{{ freq }}</el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup name="Engineering">
import * as echarts from 'echarts'
import { listLvdsSignals, getLvdsData } from '@/api/payload/lvds'

const chartRef = ref(null)
let chart = null
const signals = ref([])
const selectedSignals = ref([])
const measureSignal = ref('')
const paused = ref(false)
const sampleRate = ref(500)
const fps = ref(0)
const cursor1 = reactive({ x: '-', y: '-' })
const cursor2 = reactive({ x: '-', y: '-' })
const deltaT = ref('-')
const deltaY = ref('-')
const freq = ref('-')
let pollTimer = null
let lastFrame = performance.now()
let frameCount = 0

const colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']

async function loadSignals() {
  const res = await listLvdsSignals('7E9B')
  signals.value = res.data || []
  if (signals.value.length && !selectedSignals.value.length) {
    selectedSignals.value = signals.value.slice(0, 2).map(s => s.id)
    measureSignal.value = selectedSignals.value[0]
  }
}

function initChart() {
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 50 },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    series: []
  })
  chart.on('click', params => {
    if (!measureSignal.value) return
    if (cursor1.x === '-') {
      cursor1.x = params.value[0]
      cursor1.y = params.value[1]
    } else {
      cursor2.x = params.value[0]
      cursor2.y = params.value[1]
      const dt = Math.abs(cursor2.x - cursor1.x)
      deltaT.value = dt ? `${dt} ms` : '-'
      deltaY.value = (cursor2.y - cursor1.y).toFixed(4)
      freq.value = dt ? `${(1000 / dt).toFixed(2)} Hz` : '-'
    }
  })
}

/** 上一轮刷新尚未结束（请求慢于 500ms 轮询）时跳过，避免并发请求堆积 */
let refreshing = false

async function refreshChart() {
  if (refreshing) return
  refreshing = true
  try {
    await refreshChartOnce()
  } finally {
    refreshing = false
  }
}

async function refreshChartOnce() {
  if (paused.value || !selectedSignals.value.length) return
  const series = []
  for (let i = 0; i < selectedSignals.value.length; i++) {
    const sig = selectedSignals.value[i]
    const res = await getLvdsData({ signal: sig, limit: 500 })
    const pts = (res.data?.points || []).map(p => [p.t, p.v])
    series.push({ name: sig, type: 'line', showSymbol: false, large: true, data: pts, color: colors[i % colors.length] })
  }
  // 请求返回前页面可能已卸载（chart 已 dispose 并置空）
  if (!chart) return
  chart.setOption({ series })
  frameCount++
  const now = performance.now()
  if (now - lastFrame >= 1000) {
    fps.value = frameCount
    frameCount = 0
    lastFrame = now
  }
}

function clearSignals() {
  selectedSignals.value = []
}

function onResize() {
  chart?.resize()
}

onMounted(async () => {
  await loadSignals()
  initChart()
  refreshChart()
  // keep-alive 下 onActivated 会在 await 期间先启动轮询；不能再覆盖句柄，否则旧定时器永远清不掉
  if (!pollTimer) pollTimer = setInterval(refreshChart, 500)
  window.addEventListener('resize', onResize)
})
onActivated(() => {
  if (!pollTimer) pollTimer = setInterval(refreshChart, 500)
})
onDeactivated(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  chart?.dispose()
  chart = null
  window.removeEventListener('resize', onResize)
})
</script>

<style scoped>
.lvds-top { display: flex; gap: 16px; align-items: center; margin-bottom: 12px; }
.chart-box { width: 100%; height: calc(100vh - 160px); }
.signal-item { margin-bottom: 6px; }
</style>
