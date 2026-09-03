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
            <el-table-column prop="value" label="值" width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="row.valueClass || undefined">{{ row.value }}</span>
              </template>
            </el-table-column>
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
/** 是否已加载出真实图像（否则画默认黑方） */
const hasImage = ref(false)
/** 无图时默认黑方逻辑分辨率 */
const DEFAULT_PLACEHOLDER = 400
/** 当前显示图逻辑分辨率（有图用像素；无图固定 DEFAULT_PLACEHOLDER） */
const displayWh = reactive({ w: DEFAULT_PLACEHOLDER, h: DEFAULT_PLACEHOLDER })
/** 缩放倍数；1 = 1 CSS 像素对应 1 图像像素 */
const scale = ref(1)
/** 平移偏移（相对居中后的额外位移） */
const offset = reactive({ x: 0, y: 0 })
const dragging = ref(false)
/** 拖拽起点：鼠标位置 + 当时的 offset */
const dragStart = reactive({ x: 0, y: 0, ox: 0, oy: 0 })
/** outside=true → nan,nan；初始化显示 0,0 */
const cursor = reactive({ x: 0, y: 0, gray: null, outside: false })
const fpsText = ref('-')
/** 近 3s 帧时间戳，用于估算帧率 */
const recentTs = ref([])

/** 当前已加载的 Image 元素 */
let imgEl = null
/** 离屏像素，用于鼠标处灰阶采样 */
let grayData = null
let resizeObs = null
/** 上一帧图像像素尺寸；默认黑方 400×400 也计入，同分辨率替换时保留缩放/平移 */
let lastImageWh = { w: DEFAULT_PLACEHOLDER, h: DEFAULT_PLACEHOLDER }

const resText = computed(() => {
  if (hasImage.value) {
    const w = Number(props.width) || imgEl?.width || displayWh.w
    const h = Number(props.height) || imgEl?.height || displayWh.h
    return `${w}×${h}`
  }
  const ph = placeholderLogicalSize()
  return `${ph.w}×${ph.h}`
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

/** 拼接 D8/D9 两侧统计：有值的用 ` / ` 连接 */
function joinStat(...parts) {
  return parts.filter(p => p != null && String(p).trim() !== '').join(' / ') || ''
}

const metaRows = computed(() => [
  { label: '图片刷新时间', value: refreshTimeText.value, valueClass: 'cam-refresh-time' },
  { label: '帧率', value: fpsText.value },
  { label: '分辨率', value: resText.value },
  { label: '图像索引', value: props.imageNo ?? '-' },
  { label: '坐标', value: coordText.value },
  { label: '灰阶', value: grayText.value }
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

/** 左侧信息表：帧率/分辨率等元数据 + D8/D9 统计 */
const allRows = computed(() => [...metaRows.value, ...statsRows.value])

/** 双击复位：缩放 1（1:1 像素）、居中，不铺满视口 */
function resetView() {
  scale.value = 1
  offset.x = 0
  offset.y = 0
  draw()
}

/** 用近 3s 帧间隔估算帧率 */
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

/** 图像逻辑宽高（props 优先，否则用已加载图） */
function imageLogicalSize() {
  const w = Number(props.width) || imgEl?.naturalWidth || imgEl?.width || 0
  const h = Number(props.height) || imgEl?.naturalHeight || imgEl?.height || 0
  return { w: Math.max(1, w), h: Math.max(1, h) }
}

/** 有图/无图都按实际像素×缩放居中；scale=1 即 1 CSS 像素 = 1 图像像素，不铺满视口 */
function layoutImage(cw, ch) {
  const s = scale.value
  const { w, h } = hasImage.value ? imageLogicalSize() : placeholderLogicalSize()
  const drawW = w * s
  const drawH = h * s
  const dx = (cw - drawW) / 2 + offset.x
  const dy = (ch - drawH) / 2 + offset.y
  return { baseW: w, baseH: h, drawW, drawH, dx, dy, s }
}

/** 无图时默认黑方尺寸：优先 props 宽高（开图前已按目标分辨率同步），否则 400 */
function placeholderLogicalSize() {
  const w = Number(props.width) || 0
  const h = Number(props.height) || 0
  if (w > 0 && h > 0) return { w, h }
  return { w: DEFAULT_PLACEHOLDER, h: DEFAULT_PLACEHOLDER }
}

/** 分辨率变化则复位缩放/平移；同尺寸替换保留当前视图 */
function applyImageSize(nw, nh) {
  const w = Math.max(1, Number(nw) || DEFAULT_PLACEHOLDER)
  const h = Math.max(1, Number(nh) || DEFAULT_PLACEHOLDER)
  const same = lastImageWh.w === w && lastImageWh.h === h
  if (!same) {
    scale.value = 1
    offset.x = 0
    offset.y = 0
  }
  lastImageWh = { w, h }
}

/** 加载 data URL；空 src 则回到默认黑方（尺寸变化时同样复位缩放/平移） */
function loadImage(src) {
  if (!src) {
    hasImage.value = false
    imgEl = null
    grayData = null
    const ph = placeholderLogicalSize()
    applyImageSize(ph.w, ph.h)
    draw()
    return
  }
  const img = new Image()
  img.onload = () => {
    imgEl = img
    hasImage.value = true
    applyImageSize(img.width, img.height)
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
    const ph = placeholderLogicalSize()
    applyImageSize(ph.w, ph.h)
    draw()
  }
  img.src = src
}

/** 图像坐标 → 视口 CSS 像素（质心十字用） */
function imageToClient(ix, iy, cw, ch) {
  const { drawW, drawH, dx, dy } = layoutImage(cw, ch)
  const iw = imgEl?.width || Number(props.width) || displayWh.w
  const ih = imgEl?.height || Number(props.height) || displayWh.h
  if (!iw || !ih) return null
  return {
    x: dx + (ix / iw) * drawW,
    y: dy + (iy / ih) * drawH
  }
}

/** 在图像坐标处画红色十字星（不随缩放变粗） */
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

/** 按 DPR 铺满视口：灰底 + 图/黑方 + 质心 */
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

  const { baseW, baseH, drawW, drawH, dx, dy } = layoutImage(cw, ch)
  displayWh.w = baseW
  displayWh.h = baseH
  ctx.imageSmoothingEnabled = false

  if (imgEl && hasImage.value) {
    ctx.drawImage(imgEl, dx, dy, drawW, drawH)
  } else {
    // 占位黑方 + 十字，避免与真实全黑图混淆（仅初始无图时使用）
    ctx.fillStyle = '#000000'
    ctx.fillRect(dx, dy, drawW, drawH)
    const midX = dx + drawW / 2
    const midY = dy + drawH / 2
    const pad = Math.max(2, Math.min(drawW, drawH) * 0.08)
    ctx.strokeStyle = '#c0c4cc'
    ctx.lineWidth = Math.max(1, Math.min(2, Math.min(drawW, drawH) * 0.02))
    ctx.beginPath()
    ctx.moveTo(dx + pad, midY)
    ctx.lineTo(dx + drawW - pad, midY)
    ctx.moveTo(midX, dy + pad)
    ctx.lineTo(midX, dy + drawH - pad)
    ctx.stroke()
  }
  drawCentroidMark(ctx, cw, ch)
}

/** 鼠标视口坐标 → 图像像素；落在图外返回 null */
function clientToImage(clientX, clientY) {
  const vp = viewportRef.value
  if (!vp) return null
  const rect = vp.getBoundingClientRect()
  const x = clientX - rect.left
  const y = clientY - rect.top
  const cw = vp.clientWidth
  const ch = vp.clientHeight
  const { baseW, baseH, drawW, drawH, dx, dy } = layoutImage(cw, ch)
  if (x < dx || y < dy || x >= dx + drawW || y >= dy + drawH) return null

  const lx = (x - dx) / drawW
  const ly = (y - dy) / drawH

  if (hasImage.value && imgEl) {
    const iw = imgEl.width || props.width || baseW
    const ih = imgEl.height || props.height || baseH
    const ix = Math.min(iw - 1, Math.max(0, Math.floor(lx * iw)))
    const iy = Math.min(ih - 1, Math.max(0, Math.floor(ly * ih)))
    return { ix, iy, fromImage: true }
  }

  const ix = Math.min(baseW - 1, Math.max(0, Math.floor(lx * baseW)))
  const iy = Math.min(baseH - 1, Math.max(0, Math.floor(ly * baseH)))
  return { ix, iy, fromImage: false }
}

/** 采样 R 通道作为灰阶（灰度图） */
function sampleGray(ix, iy) {
  if (!grayData) return null
  const i = (iy * grayData.width + ix) * 4
  return grayData.data[i]
}

/** 鼠标离开图像：坐标显示 nan, nan */
function setOutside() {
  cursor.outside = true
  cursor.x = 0
  cursor.y = 0
  cursor.gray = null
}

/** 更新光标处图像坐标与灰阶 */
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

/** 滚轮缩放：以鼠标点为锚，限制 0.2–32 倍 */
function onWheel(e) {
  const vp = viewportRef.value
  if (!vp) return
  const rect = vp.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const cw = vp.clientWidth
  const ch = vp.clientHeight
  const s0 = scale.value
  const factor = e.deltaY < 0 ? 1.1 : 0.9
  const s1 = Math.min(32, Math.max(0.2, s0 * factor))
  if (s1 === s0) return

  const before = layoutImage(cw, ch)
  const lx = before.drawW ? (mx - before.dx) / before.drawW : 0.5
  const ly = before.drawH ? (my - before.dy) / before.drawH : 0.5
  const drawW1 = before.drawW * (s1 / s0)
  const drawH1 = before.drawH * (s1 / s0)
  scale.value = s1
  offset.x = mx - lx * drawW1 - (cw - drawW1) / 2
  offset.y = my - ly * drawH1 - (ch - drawH1) / 2
  draw()
  updateCursor(e.clientX, e.clientY)
}

/** 左键按下开始拖拽平移 */
function onMouseDown(e) {
  if (e.button !== 0) return
  dragging.value = true
  dragStart.x = e.clientX
  dragStart.y = e.clientY
  dragStart.ox = offset.x
  dragStart.oy = offset.y
}

/** 移动：更新光标；拖拽中同步 offset */
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

/** 离开视口：结束拖拽并清除坐标 */
function onMouseLeave() {
  dragging.value = false
  setOutside()
}

watch(
  () => props.imageSrc,
  (src) => loadImage(src)
)

/** 开图前目标分辨率变化：无真图时按新尺寸画黑方，并复位缩放/平移 */
watch(
  () => [props.width, props.height],
  () => {
    if (hasImage.value) return
    const ph = placeholderLogicalSize()
    applyImageSize(ph.w, ph.h)
    draw()
  }
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

.cam-refresh-time {
  color: #409eff;
  font-variant-numeric: tabular-nums;
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
