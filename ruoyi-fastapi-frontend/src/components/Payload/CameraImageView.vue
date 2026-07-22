<template>
  <div class="cam-image-view">
    <div class="info-bar">
      <span class="info-item info-fps"><em>帧率:</em> {{ fpsText }}</span>
      <span class="info-item info-res"><em>分辨率:</em> {{ resText }}</span>
      <span class="info-item info-no"><em>序号:</em> {{ imageNo ?? '-' }}</span>
      <span class="info-item info-coord"><em>坐标:</em> {{ coordText }}</span>
      <span class="info-item info-gray"><em>灰阶:</em> {{ grayText }}</span>
      <span class="info-item info-refresh"><em>刷新时间:</em> {{ refreshTimeText }}</span>
      <span class="hint">滚轮缩放 · 拖拽平移 · 双击复位</span>
    </div>
    <div
      ref="viewportRef"
      class="viewport"
      @wheel.prevent="onWheel"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseLeave"
      @dblclick="resetView"
    >
      <canvas ref="canvasRef" class="canvas" />
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  /** data URL 或空 */
  imageSrc: { type: String, default: '' },
  width: { type: Number, default: 0 },
  height: { type: Number, default: 0 },
  imageNo: { type: [Number, String], default: null },
  /** 用于估算帧率的帧时间戳(ms) */
  frameTs: { type: Number, default: 0 },
  /** 图片获取时间展示文本 */
  refreshTime: { type: String, default: '-' }
})

const viewportRef = ref(null)
const canvasRef = ref(null)
const hasImage = ref(false)
/** 当前显示图逻辑分辨率（默认黑方=视口高度边长） */
const displayWh = reactive({ w: 0, h: 0 })
const scale = ref(1)
const offset = reactive({ x: 0, y: 0 })
const dragging = ref(false)
const dragStart = reactive({ x: 0, y: 0, ox: 0, oy: 0 })
/** outside=true → nan,nan；初始化显示 0,0 */
const cursor = reactive({ x: 0, y: 0, gray: null, outside: false })
const fpsText = ref('-')
const recentTs = ref([])

let imgEl = null
let grayData = null
let resizeObs = null

const resText = computed(() => {
  if (hasImage.value) {
    const w = Number(props.width) || imgEl?.width || displayWh.w
    const h = Number(props.height) || imgEl?.height || displayWh.h
    return `${w}×${h}`
  }
  return `${displayWh.w || 0}×${displayWh.h || 0}`
})

const coordText = computed(() => {
  if (cursor.outside) return 'nan, nan'
  return `${cursor.x}, ${cursor.y}`
})

const grayText = computed(() => {
  if (cursor.outside) return '-'
  if (!hasImage.value) return '0'
  return cursor.gray == null ? '-' : String(cursor.gray)
})

const refreshTimeText = computed(() => props.refreshTime || '-')

function resetView() {
  scale.value = 1
  offset.x = 0
  offset.y = 0
  draw()
}

function updateFps(ts) {
  if (!ts) return
  const arr = recentTs.value.filter(t => ts - t < 3000)
  arr.push(ts)
  recentTs.value = arr
  if (arr.length >= 2) {
    const dt = (arr[arr.length - 1] - arr[0]) / (arr.length - 1)
    fpsText.value = dt > 0 ? (1000 / dt).toFixed(1) : '-'
  }
}

/** 正方形边长 = 背景区高度；水平居中后再叠加缩放/平移 */
function layoutSquare(cw, ch) {
  const base = Math.max(1, ch)
  const s = scale.value
  const side = base * s
  const dx = (cw - side) / 2 + offset.x
  const dy = (ch - side) / 2 + offset.y
  return { base, side, dx, dy, s }
}

function loadImage(src) {
  if (!src) {
    hasImage.value = false
    imgEl = null
    grayData = null
    draw()
    return
  }
  const img = new Image()
  img.onload = () => {
    imgEl = img
    hasImage.value = true
    try {
      const off = document.createElement('canvas')
      off.width = img.width
      off.height = img.height
      const ctx = off.getContext('2d', { willReadFrequently: true })
      ctx.drawImage(img, 0, 0)
      grayData = ctx.getImageData(0, 0, img.width, img.height)
    } catch {
      grayData = null
    }
    draw()
  }
  img.onerror = () => {
    hasImage.value = false
    imgEl = null
    grayData = null
    draw()
  }
  img.src = src
}

function draw() {
  const canvas = canvasRef.value
  const vp = viewportRef.value
  if (!canvas || !vp) return
  const dpr = window.devicePixelRatio || 1
  const cw = vp.clientWidth
  const ch = vp.clientHeight
  canvas.width = Math.max(1, Math.floor(cw * dpr))
  canvas.height = Math.max(1, Math.floor(ch * dpr))
  canvas.style.width = `${cw}px`
  canvas.style.height = `${ch}px`
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  // 灰色背景
  ctx.fillStyle = '#9e9e9e'
  ctx.fillRect(0, 0, cw, ch)

  const { base, side, dx, dy } = layoutSquare(cw, ch)
  displayWh.w = base
  displayWh.h = base
  ctx.imageSmoothingEnabled = false

  if (imgEl && hasImage.value) {
    ctx.drawImage(imgEl, dx, dy, side, side)
  } else {
    // 无数据时默认纯黑正方形
    ctx.fillStyle = '#000000'
    ctx.fillRect(dx, dy, side, side)
  }
}

/**
 * 视口坐标 → 原始图像坐标（不受缩放视觉影响，换算到逻辑像素）。
 * 无图像时返回控件内坐标（以正方形逻辑边长 base 为范围）。
 * 不在图像上返回 null。
 */
function clientToImage(clientX, clientY) {
  const vp = viewportRef.value
  if (!vp) return null
  const rect = vp.getBoundingClientRect()
  const x = clientX - rect.left
  const y = clientY - rect.top
  const cw = vp.clientWidth
  const ch = vp.clientHeight
  const { base, side, dx, dy } = layoutSquare(cw, ch)
  if (x < dx || y < dy || x >= dx + side || y >= dy + side) return null

  const lx = (x - dx) / side
  const ly = (y - dy) / side

  if (hasImage.value && imgEl) {
    const iw = imgEl.width || props.width || base
    const ih = imgEl.height || props.height || base
    const ix = Math.min(iw - 1, Math.max(0, Math.floor(lx * iw)))
    const iy = Math.min(ih - 1, Math.max(0, Math.floor(ly * ih)))
    return { ix, iy, fromImage: true }
  }

  const ix = Math.min(base - 1, Math.max(0, Math.floor(lx * base)))
  const iy = Math.min(base - 1, Math.max(0, Math.floor(ly * base)))
  return { ix, iy, fromImage: false }
}

function sampleGray(ix, iy) {
  if (!grayData) return null
  const i = (iy * grayData.width + ix) * 4
  return grayData.data[i]
}

function setOutside() {
  cursor.outside = true
  cursor.x = 0
  cursor.y = 0
  cursor.gray = null
}

function updateCursor(clientX, clientY) {
  const pos = clientToImage(clientX, clientY)
  if (!pos) {
    setOutside()
    return
  }
  cursor.outside = false
  cursor.x = pos.ix
  cursor.y = pos.iy
  cursor.gray = pos.fromImage ? sampleGray(pos.ix, pos.iy) : 0
}

function onWheel(e) {
  const factor = e.deltaY < 0 ? 1.1 : 0.9
  scale.value = Math.min(32, Math.max(0.2, scale.value * factor))
  draw()
  updateCursor(e.clientX, e.clientY)
}

function onMouseDown(e) {
  if (e.button !== 0) return
  dragging.value = true
  dragStart.x = e.clientX
  dragStart.y = e.clientY
  dragStart.ox = offset.x
  dragStart.oy = offset.y
}

function onMouseMove(e) {
  updateCursor(e.clientX, e.clientY)
  if (!dragging.value) return
  offset.x = dragStart.ox + (e.clientX - dragStart.x)
  offset.y = dragStart.oy + (e.clientY - dragStart.y)
  draw()
  updateCursor(e.clientX, e.clientY)
}

function onMouseUp() {
  dragging.value = false
}

function onMouseLeave() {
  dragging.value = false
  setOutside()
}

watch(
  () => props.imageSrc,
  (src) => loadImage(src)
)

watch(
  () => props.frameTs,
  (ts) => updateFps(ts)
)

onMounted(() => {
  cursor.outside = false
  cursor.x = 0
  cursor.y = 0
  cursor.gray = null
  loadImage(props.imageSrc)
  draw()
  if (typeof ResizeObserver !== 'undefined' && viewportRef.value) {
    resizeObs = new ResizeObserver(() => draw())
    resizeObs.observe(viewportRef.value)
  } else {
    window.addEventListener('resize', draw)
  }
})

onUnmounted(() => {
  if (resizeObs) {
    resizeObs.disconnect()
    resizeObs = null
  }
  window.removeEventListener('resize', draw)
})
</script>

<style scoped>
.cam-image-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.info-bar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0;
  padding: 6px 10px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  border-bottom: 1px solid var(--el-border-color);
  background: var(--el-fill-color-light);
  flex-shrink: 0;
  overflow: hidden;
}
.info-item {
  display: inline-flex;
  align-items: baseline;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: clip;
  box-sizing: border-box;
  padding-right: 12px;
}
.info-item em {
  font-style: normal;
  margin-right: 4px;
  flex-shrink: 0;
}
/* 固定各字段槽位，避免坐标位数变化带动后续项左右跳动 */
.info-fps {
  width: 80px;
}
.info-res {
  width: 120px;
}
.info-no {
  width: 80px;
}
.info-coord {
  width: 100px;
}
.info-gray {
  width: 80px;
}
.info-refresh {
  width: 210px;
}
.info-bar .hint {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  white-space: nowrap;
}
.viewport {
  position: relative;
  flex: 1;
  min-height: 200px;
  cursor: crosshair;
  overflow: hidden;
  background: #9e9e9e;
}
.canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
