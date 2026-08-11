<template>
  <div class="cam-image-view">
    <div class="cam-side-left">
      <div class="cam-side-hint">图像操作：滚轮缩放 · 拖拽平移 · 双击复位</div>
      <div class="cam-side-left-body">
        <div v-if="$slots.toolbar" class="cam-toolbar-col">
          <slot name="toolbar" />
        </div>
        <div class="cam-table-wrap">
          <el-table :data="allRows" border size="small" class="cam-data-table" :show-header="false">
            <el-table-column prop="label" label="项" width="120" class-name="col-label" />
            <el-table-column prop="value" label="值" width="160" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
    </div>
    <div class="cam-side-right">
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
  refreshTime: { type: String, default: '-' },
  /** 勾选后在图像上绘制质心十字星（图像坐标，非缩放后坐标） */
  showCentroid: { type: Boolean, default: false },
  /** { x, y } 质心图像坐标；null 时不绘制 */
  centroid: { type: Object, default: null },
  /** D8/D9 遥测统计 */
  tmStats: {
    type: Object,
    default: () => ({
      tableLabel: '',
      coordD8: '',
      coordD9: '',
      energyD8: '',
      energyD9: '',
      overThD8: '',
      overThD9: '',
      satD8: '',
      satD9: '',
      grayD8: '',
      grayD9: ''
    })
  }
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

function joinStat(...parts) {
  return parts.filter(p => p != null && String(p).trim() !== '').join(' / ') || ''
}

const metaRows = computed(() => [
  { label: '帧率', value: fpsText.value },
  { label: '分辨率', value: resText.value },
  { label: '序号', value: props.imageNo ?? '-' },
  { label: '坐标', value: coordText.value },
  { label: '灰阶', value: grayText.value },
  { label: '图片刷新时间', value: refreshTimeText.value }
])

const statsRows = computed(() => {
  const s = props.tmStats || {}
  return [
    { label: '遥测表', value: s.tableLabel || '' },
    { label: '坐标', value: joinStat(s.coordD8, s.coordD9) },
    { label: '光斑能量(dBm)', value: joinStat(s.energyD8, s.energyD9) },
    { label: '过阈值像元数', value: joinStat(s.overThD8, s.overThD9) },
    { label: '饱和像元数', value: joinStat(s.satD8, s.satD9) },
    { label: '平均灰度值', value: joinStat(s.grayD8, s.grayD9) }
  ]
})

const allRows = computed(() => [...metaRows.value, ...statsRows.value])

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

function imageToClient(ix, iy, cw, ch) {
  const { side, dx, dy } = layoutSquare(cw, ch)
  const iw = imgEl?.width || Number(props.width) || displayWh.w
  const ih = imgEl?.height || Number(props.height) || displayWh.h
  if (!iw || !ih) return null
  return {
    x: dx + (ix / iw) * side,
    y: dy + (iy / ih) * side
  }
}

function drawCentroidMark(ctx, cw, ch) {
  if (!props.showCentroid) return
  const c = props.centroid
  const ix = Number(c?.x)
  const iy = Number(c?.y)
  if (!Number.isFinite(ix) || !Number.isFinite(iy)) return
  const pos = imageToClient(ix, iy, cw, ch)
  if (!pos) return
  const half = 5
  ctx.save()
  ctx.strokeStyle = '#ff0000'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(pos.x - half, pos.y)
  ctx.lineTo(pos.x + half, pos.y)
  ctx.moveTo(pos.x, pos.y - half)
  ctx.lineTo(pos.x, pos.y + half)
  ctx.stroke()
  ctx.restore()
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

  ctx.fillStyle = '#9e9e9e'
  ctx.fillRect(0, 0, cw, ch)

  const { base, side, dx, dy } = layoutSquare(cw, ch)
  displayWh.w = base
  displayWh.h = base
  ctx.imageSmoothingEnabled = false

  if (imgEl && hasImage.value) {
    ctx.drawImage(imgEl, dx, dy, side, side)
  } else {
    ctx.fillStyle = '#000000'
    ctx.fillRect(dx, dy, side, side)
  }
  drawCentroidMark(ctx, cw, ch)
}

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

watch(
  () => [props.showCentroid, props.centroid?.x, props.centroid?.y],
  () => draw()
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
  flex-direction: row;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.cam-side-left {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
}

.cam-side-hint {
  flex-shrink: 0;
  padding: 6px 10px 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  text-align: right;
}

.cam-side-left-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 28px;
  padding: 8px 10px 8px;
  overflow: hidden;
}

.cam-toolbar-col {
  flex: 0 0 auto;
  width: auto;
  display: flex;
  flex-direction: column;
}

.cam-table-wrap {
  flex: 0 0 auto;
  width: 280px;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
}

.cam-data-table {
  width: 280px !important;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.cam-data-table :deep(.el-table__inner-wrapper::before),
.cam-data-table :deep(.el-table__border-left-patch) {
  display: none;
}

.cam-data-table :deep(.el-table__body),
.cam-data-table :deep(.el-table__header) {
  width: 100% !important;
}

.cam-data-table :deep(.el-scrollbar__wrap) {
  overflow-x: hidden !important;
}

.cam-data-table :deep(.el-scrollbar__bar.is-horizontal) {
  display: none !important;
}

.cam-data-table :deep(.col-label) {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  font-weight: 500;
}

.cam-data-table :deep(.el-table__cell) {
  padding: 4px 6px;
}

.cam-side-right {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  background: #9e9e9e;
}

.viewport {
  position: relative;
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
  cursor: crosshair;
  overflow: hidden;
}

.canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
