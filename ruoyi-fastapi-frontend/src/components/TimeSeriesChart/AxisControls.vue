<template>
  <div v-show="visible" class="axis-ctrl-layer">
    <div class="y-axis-controls">
      <div class="y-ctrl-cluster">
        <button type="button" class="y-ctrl-btn" title="最大值增加" @click="$emit('nudge-max', 1)">+</button>
        <button type="button" class="y-ctrl-btn" title="最大值减少" @click="$emit('nudge-max', -1)">−</button>
      </div>
      <div class="y-ctrl-cluster">
        <button type="button" class="y-ctrl-btn" title="Y轴上移半格" @click="$emit('pan', 1)">
          <el-icon><CaretTop /></el-icon>
        </button>

        <button type="button" class="y-ctrl-btn" title="放大" @click="$emit('zoom', zoomIn)">+</button>
        <button type="button" class="y-ctrl-btn y-ctrl-auto" title="Y坐标轴自适应" @click="$emit('fit')">A</button>
        <button type="button" class="y-ctrl-btn" title="缩小" @click="$emit('zoom', zoomOut)">-</button>

        <button type="button" class="y-ctrl-btn" title="Y轴下移半格" @click="$emit('pan', -1)">
          <el-icon><CaretBottom /></el-icon>
        </button>
      </div>
      <div class="y-ctrl-cluster-bottom y-ctrl-cluster">
        <button type="button" class="y-ctrl-btn" title="最小值增加" @click="$emit('nudge-min', 1)">+</button>
        <button type="button" class="y-ctrl-btn" title="最小值减少" @click="$emit('nudge-min', -1)">−</button>
      </div>
    </div>
    <div class="xy-wheel-cluster">
      <button
        type="button"
        class="y-ctrl-btn y-ctrl-wheel"
        :class="{ 'is-on': zoomY }"
        :aria-pressed="zoomY ? 'true' : 'false'"
        title="启用滚轮进行Y轴缩放"
        @click="toggleZoomY"
      >
        <span class="y-ctrl-wheel-text">Y</span>
      </button>
      <div class="x-ctrl-row">
        <button
          type="button"
          class="y-ctrl-btn y-ctrl-wheel"
          :class="{ 'is-on': zoomX }"
          :aria-pressed="zoomX ? 'true' : 'false'"
          title="启用滚轮进行X轴缩放"
          @click="toggleZoomX"
        >
          <span class="y-ctrl-wheel-text">X</span>
        </button>
        <button type="button" class="y-ctrl-btn" title="移到数据起始位置" @click="$emit('jump-start')">
          <el-icon><CaretLeft /></el-icon>
        </button>
        <button type="button" class="y-ctrl-btn" title="跟随最新" @click="$emit('follow-latest')">
          <el-icon><CaretRight /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { CaretTop, CaretBottom, CaretLeft, CaretRight } from '@element-plus/icons-vue'
import { Y_ZOOM_IN, Y_ZOOM_OUT } from './yAxisRange'
import { zoomX, zoomY } from './zoomWheelPrefs'

defineProps({
  visible: { type: Boolean, default: true }
})

defineEmits(['pan', 'nudge-max', 'nudge-min', 'zoom', 'fit', 'jump-start', 'follow-latest'])

const zoomIn = Y_ZOOM_IN
const zoomOut = Y_ZOOM_OUT

function toggleZoomY() {
  zoomY.value = !zoomY.value
}

function toggleZoomX() {
  zoomX.value = !zoomX.value
}
</script>

<style scoped>
.axis-ctrl-layer {
  pointer-events: none;
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  z-index: 3;
}
.y-axis-controls {
  pointer-events: none;
  position: absolute;
  left: 0;
  top: 0;
  bottom: 62px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
}
.xy-wheel-cluster {
  pointer-events: none;
  position: absolute;
  left: 0;
  bottom: 6px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
}
.x-ctrl-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0;
}
.y-ctrl-cluster {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}
.y-ctrl-cluster-bottom {
  transform: translateY(10px);
}
.y-ctrl-btn {
  pointer-events: auto;
  width: 16px;
  height: 16px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 2px;
  background: transparent;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  font-family: inherit;
}
.y-ctrl-auto {
  font-size: 11px;
}
.y-ctrl-wheel {
  font-size: 11px;
}
.y-ctrl-wheel-text {
  display: inline-block;
  padding: 0 1px;
  line-height: 1.15;
  border-radius: 2px;
}
.y-ctrl-wheel.is-on .y-ctrl-wheel-text {
  color: var(--el-color-primary);
  font-weight: 600;
  background: var(--el-color-primary-light-7);
}
.y-ctrl-btn :deep(.el-icon) {
  font-size: 14px;
}
.y-ctrl-btn:hover:not(.y-ctrl-wheel) {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}
.y-ctrl-wheel:hover .y-ctrl-wheel-text {
  color: var(--el-color-primary);
}
</style>
