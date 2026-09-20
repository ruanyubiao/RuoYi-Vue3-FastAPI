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
      <div class="side-row">
        <span class="side-label">行程</span>
        <el-radio-group v-model="travelLocal" size="small" class="travel-group">
          <el-radio-button :label="JOYSTICK_TRAVEL_CIRCLE">圆形</el-radio-button>
          <el-radio-button :label="JOYSTICK_TRAVEL_SQUARE">方形</el-radio-button>
        </el-radio-group>
      </div>
      <div class="side-row">
        <span class="side-label">锁定</span>
        <el-checkbox :model-value="locked" @update:model-value="onLockChange" />
      </div>
      <div class="param">方位速度 {{ fmt(az) }} °/s</div>
      <div class="param">俯仰速度 {{ fmt(el) }} °/s</div>
    </div>
  </div>
</template>

<script setup>
/**
 * 速度摇杆。travel=square 方形行程（对角可同时满量程）；travel=circle 圆形行程。
 * 锁定：松开后旋钮不回中；取消锁定则回中。
 */
import padUrl from '@/assets/images/joystick/pad.png'
import knobUrl from '@/assets/images/joystick/knob.png'
import {
  JOYSTICK_TRAVEL_CIRCLE,
  JOYSTICK_TRAVEL_SQUARE,
  normalizeTravel,
  pointerToSpeed,
  speedToStick
} from '@/utils/virtualJoystick'

const props = defineProps({
  az: { type: Number, default: 0 },
  el: { type: Number, default: 0 },
  locked: { type: Boolean, default: false },
  /** square 方形行程；circle 圆形行程。默认圆形。 */
  travel: {
    type: String,
    default: JOYSTICK_TRAVEL_CIRCLE,
    validator: (v) => v === JOYSTICK_TRAVEL_SQUARE || v === JOYSTICK_TRAVEL_CIRCLE
  }
})

const emit = defineEmits(['update:az', 'update:el', 'update:locked', 'update:travel', 'update:engaging', 'change'])

const padRef = ref(null)
const dragging = ref(false)
const dragPos = ref({ x: 0, y: 0 })
const travelLocal = ref(normalizeTravel(props.travel))

const travelOpt = computed(() => ({ travel: travelLocal.value }))

const stick = computed(() => {
  if (dragging.value) return dragPos.value
  return speedToStick(props.az, props.el, travelOpt.value)
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
  const next = pointerToSpeed(dx, dy, travelOpt.value)
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

watch(
  () => props.travel,
  (v) => {
    const n = normalizeTravel(v)
    if (n !== travelLocal.value) travelLocal.value = n
  }
)

watch(travelLocal, (v) => {
  emit('update:travel', normalizeTravel(v))
  if (!dragging.value) return
  const next = pointerToSpeed(dragPos.value.x, dragPos.value.y, { travel: normalizeTravel(v) })
  dragPos.value = { x: next.x, y: next.y }
  emitSpeed(next)
})
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
  min-width: 196px;
  flex-shrink: 0;
}
.side-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.side-label {
  width: 2em;
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1;
  color: var(--el-text-color-primary);
}
.travel-group {
  display: inline-flex;
}
.side-row :deep(.el-checkbox__label) {
  display: none;
}
.param {
  font-size: 13px;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-primary);
}
</style>
