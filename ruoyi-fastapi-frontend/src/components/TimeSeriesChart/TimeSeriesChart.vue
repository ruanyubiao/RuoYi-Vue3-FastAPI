<template>
  <div class="ts-chart-root">
    <div ref="chartRef" class="chart-box" />
    <AxisControls
      :visible="showControls"
      @pan="api.panYAxis"
      @nudge-max="api.nudgeYMaxBound"
      @nudge-min="api.nudgeYMinBound"
      @zoom="onZoomYCenter"
      @fit="api.fitYAxis"
      @jump-start="onJumpStart"
      @follow-latest="onFollowLatest"
    />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTimeSeriesChart } from './useTimeSeriesChart'
import AxisControls from './AxisControls.vue'
import { zoomX, zoomY } from './zoomWheelPrefs'

const emit = defineEmits(['viewChange'])
const props = defineProps({
  getSeries: { type: Function, required: true },
  getSeriesPoints: { type: Function, required: true },
  showControls: { type: Boolean, default: false },
  defaultViewWindowMs: { type: Number, default: undefined }
})

const chartRef = ref(null)

const api = useTimeSeriesChart({
  chartRef,
  getSeries: () => props.getSeries() || [],
  getSeriesPoints: () => props.getSeriesPoints() || [],
  zoomX,
  zoomY,
  defaultViewWindowMs: props.defaultViewWindowMs
})

watch([zoomX, zoomY], () => api.refreshZoomBindings())

function onZoomYCenter(factor) {
  const f = Number(factor)
  if (!(f > 0) || !Number.isFinite(f)) return
  api.zoomYAtCenter(f)
}

function onFollowLatest() {
  api.followLatest()
  emit('viewChange')
}

function onJumpStart() {
  api.jumpToStart()
  emit('viewChange')
}

onMounted(() => {
  api.init()
  window.addEventListener('resize', api.resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', api.resize)
  api.dispose()
})

defineExpose(api)
</script>

<style scoped>
.ts-chart-root {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.chart-box {
  width: 100%;
  height: 100%;
}
</style>
