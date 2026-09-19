<template>
  <div class="cpazx-joystick">
    <div
      ref="padRef"
      class="pad"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
      @pointercancel="onUp"
    >
      <img class="pad-bg" :src="padUrl" alt="" draggable="false" />
      <img class="knob" :src="knobUrl" alt="" draggable="false" :style="knobStyle" />
    </div>
    <div class="side">
      <el-checkbox :model-value="locked" @update:model-value="onLockChange">锁定</el-checkbox>
      <div class="param">方位速度 {{ fmt(az) }} °/s</div>
      <div class="param">俯仰速度 {{ fmt(el) }} °/s</div>
    </div>
  </div>
</template>

<script setup>
/**
 * CPA 指向速度摇杆：圆盘拖动对应 CP06 方位/俯仰角速度。
 * 锁定：松开后旋钮不回中；取消锁定则回中。
 */
import padUrl from '@/assets/images/joystick/pad.png'
import knobUrl from '@/assets/images/joystick/knob.png'
import { pointerToSpeed, speedToStick } from '@/utils/virtualJoystick'

const props = defineProps({
  az: { type: Number, default: 0 },
  el: { type: Number, default: 0 },
  locked: { type: Boolean, default: false }
})

const emit = defineEmits(['update:az', 'update:el', 'update:locked', 'update:engaging', 'change'])

const padRef = ref(null)
const dragging = ref(false)
const dragPos = ref({ x: 0, y: 0 })

const stick = computed(() => {
  if (dragging.value) return dragPos.value
  return speedToStick(props.az, props.el)
})

const knobStyle = computed(() => ({
  transform: `translate(${stick.value.x}px, ${stick.value.y}px)`
}))

function fmt(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(3) : '0.000'
}

function emitSpeed(next) {
  emit('update:az', next.az)
  emit('update:el', next.el)
  emit('change', { az: next.az, el: next.el, x: next.x, y: next.y })
}

function localPoint(ev) {
  const el = padRef.value
  if (!el) return { dx: 0, dy: 0 }
  const r = el.getBoundingClientRect()
  return {
    dx: ev.clientX - (r.left + r.width / 2),
    dy: ev.clientY - (r.top + r.height / 2)
  }
}

function applyPointer(ev) {
  const { dx, dy } = localPoint(ev)
  const next = pointerToSpeed(dx, dy)
  dragPos.value = { x: next.x, y: next.y }
  emitSpeed(next)
}

function onDown(ev) {
  if (ev.button != null && ev.button !== 0) return
  dragging.value = true
  emit('update:engaging', true)
  try {
    ev.currentTarget.setPointerCapture(ev.pointerId)
  } catch {
    /* ignore */
  }
  applyPointer(ev)
  ev.preventDefault()
}

function onMove(ev) {
  if (!dragging.value) return
  applyPointer(ev)
}

function snapCenter() {
  dragPos.value = { x: 0, y: 0 }
  emitSpeed({ az: 0, el: 0, x: 0, y: 0 })
}

function onUp() {
  if (!dragging.value) return
  if (!props.locked) snapCenter()
  dragging.value = false
  emit('update:engaging', false)
}

function onLockChange(v) {
  const on = !!v
  emit('update:locked', on)
  if (!on && !dragging.value) snapCenter()
}
</script>

<style scoped>
.cpazx-joystick {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  height: 400px;
  box-sizing: border-box;
}
.pad {
  position: relative;
  width: 400px;
  height: 400px;
  flex-shrink: 0;
  touch-action: none;
  user-select: none;
  cursor: pointer;
  overflow: visible;
}
.pad-bg,
.knob {
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
}
.pad-bg {
  width: 400px;
  height: 400px;
  display: block;
}
.knob {
  position: absolute;
  left: 146px;
  top: 146px;
  width: 108px;
  height: 108px;
  will-change: transform;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 168px;
  flex-shrink: 0;
}
.param {
  font-size: 13px;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-primary);
}
</style>
