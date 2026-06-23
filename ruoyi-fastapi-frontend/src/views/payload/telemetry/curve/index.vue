<template>
  <div class="app-container">
    <el-form :inline="true" class="mb8">
      <el-form-item label="遥测表">
        <el-select v-model="tmType" style="width: 160px" @change="onTypeChange">
          <el-option v-for="p in tmPages" :key="p.key" :label="p.name" :value="p.key" />
        </el-select>
      </el-form-item>
      <el-form-item label="遥测量">
        <el-select v-model="field" filterable style="width: 220px">
          <el-option v-for="f in fields" :key="f.id" :label="`${f.id} ${f.name}`" :value="f.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="设备">
        <el-select v-model="deviceId" style="width: 200px">
          <el-option v-for="d in deviceOptions" :key="d" :label="d" :value="d" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="confirmSubscribe">确认</el-button>
      </el-form-item>
    </el-form>
    <div ref="chartRef" class="chart-box" />
  </div>
</template>

<script setup name="PayloadTelemetryCurve">
import * as echarts from 'echarts'
import { useRoute } from 'vue-router'
import { getTelemetryConfig, getTelemetryDef } from '@/api/payload/config'
import { getTelemetryFields, subscribeTelemetryCurve, getTelemetryCurveData } from '@/api/payload/telemetry'
import { listCanChannels } from '@/api/payload/device'

const route = useRoute()
const ACTIVE_KEY = 'payload:activeDeviceId'
const chartRef = ref(null)
let chart = null
const tmPages = ref([])
const tmType = ref((route.query.type || 'FF').toString().toUpperCase())
const field = ref(route.query.field || '')
const deviceId = ref(localStorage.getItem(ACTIVE_KEY) || 'can:0:0:0')
const deviceOptions = ref([deviceId.value])
const fields = ref([])
const subscribed = ref(false)
let pollTimer = null

async function loadPages() {
  const res = await getTelemetryConfig()
  tmPages.value = (res.data.page || []).filter(p => p.key && p.key.length <= 2)
}

async function loadFields() {
  const res = await getTelemetryFields(tmType.value)
  fields.value = res.data || []
  if (!field.value && fields.value.length) field.value = fields.value[0].id
}

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 30, bottom: 60 },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    series: [{ type: 'line', showSymbol: false, data: [] }]
  })
}

async function confirmSubscribe() {
  await subscribeTelemetryCurve({ deviceId: deviceId.value, type: tmType.value, field: field.value, enabled: true })
  subscribed.value = true
  refreshData()
  if (!pollTimer) pollTimer = setInterval(refreshData, 1000)
}

async function refreshData() {
  if (!subscribed.value) return
  const res = await getTelemetryCurveData({ deviceId: deviceId.value, type: tmType.value, field: field.value, limit: 600 })
  const points = (res.data?.points || []).map(p => [p.t, p.v])
  chart?.setOption({ series: [{ data: points }] })
}

function onTypeChange() {
  loadFields()
}

onMounted(async () => {
  await loadPages()
  await loadFields()
  const ch = await listCanChannels()
  const list = (ch.data || []).map(d => d.deviceId)
  if (list.length) deviceOptions.value = list
  initChart()
  if (route.query.field) confirmSubscribe()
  window.addEventListener('resize', () => chart?.resize())
})
onUnmounted(() => {
  clearInterval(pollTimer)
  chart?.dispose()
})
</script>

<style scoped>
.chart-box { width: 100%; height: calc(100vh - 160px); }
</style>
