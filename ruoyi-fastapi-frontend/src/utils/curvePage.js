/**
 * 实时 / 归档 / 文件曲线页共用：颜色槽、series 构造、导出、截取绑定。
 */
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { buildAlignedSeriesTable, exportCsvFile, formatCsvDateTime } from '@/utils/csvExport'
import { downsampleTimeBuckets } from '@/utils/curveDownsample'

export const MAX_CURVES = 10
export const SERIES_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#2f4554'
]

export function curveKey(type, fld) {
  return `${type}:${fld}`
}

export function normalizePoints(rawPoints) {
  const out = []
  for (const p of rawPoints || []) {
    const t = Number(Array.isArray(p) ? p[0] : p?.t)
    const v = Array.isArray(p) ? p[1] : p?.v
    if (!Number.isFinite(t)) continue
    out.push([t, v])
  }
  return out
}

export function createColorSlots() {
  const keyColorIdx = {}
  const activeColorIndices = new Set()

  function acquireColor(key) {
    const prefer = keyColorIdx[key]
    if (prefer !== undefined && !activeColorIndices.has(prefer)) {
      activeColorIndices.add(prefer)
      return SERIES_COLORS[prefer]
    }
    let idx = 0
    while (idx < SERIES_COLORS.length && activeColorIndices.has(idx)) idx++
    if (idx >= SERIES_COLORS.length) idx = 0
    keyColorIdx[key] = idx
    activeColorIndices.add(idx)
    return SERIES_COLORS[idx]
  }

  function releaseColor(key) {
    const idx = keyColorIdx[key]
    if (idx === undefined) return
    activeColorIndices.delete(idx)
  }

  return { acquireColor, releaseColor }
}

export function paintSeriesPoints(points, paint) {
  const pts = Array.isArray(points) ? points : []
  const dt = Number(paint?.bucketMs)
  if (!paint || !(dt > 0) || pts.length < 3) return pts
  const dataStart = Number(pts[0]?.[0])
  const dataEnd = Number(pts[pts.length - 1]?.[0])
  if (!Number.isFinite(dataStart) || !Number.isFinite(dataEnd) || dataEnd <= dataStart) return pts
  const n = Math.max(1, Math.min(4000, Math.ceil((dataEnd - dataStart) / dt)))
  if (pts.length <= n * 2) return pts
  return downsampleTimeBuckets(pts, dataStart, dataEnd, n)
}

export function buildChartSeries(curves, paint) {
  return (curves || []).map(c => ({
    id: c.key,
    name: `${c.field} ${c.name}`,
    type: 'line',
    showSymbol: false,
    animation: false,
    large: true,
    largeThreshold: 400,
    data: paintSeriesPoints(c.points, paint),
    itemStyle: { color: c.color },
    lineStyle: { color: c.color }
  }))
}

export function useCurveChartPage(tsChart, curves, options = {}) {
  const colors = createColorSlots()
  const cropMode = computed(() => !!tsChart.value?.cropMode)

  function getChartSeries() {
    let paint = null
    if (options.livePaint) {
      const win = tsChart.value?.getTimeWindow?.()
      const width = tsChart.value?.getPlotWidth?.() || 800
      paint = {
        start: win?.start,
        end: win?.end,
        pixelWidth: width
      }
    }
    return buildChartSeries(curves.value, paint)
  }

  function getChartPoints() {
    return curves.value
  }

  function onToggleCrop() {
    tsChart.value?.toggleCropMode({ hasSeries: (curves.value || []).length > 0 })
  }

  return {
    ...colors,
    cropMode,
    getChartSeries,
    getChartPoints,
    onToggleCrop
  }
}

export function exportChartWindowCsv({ tsChart, curves, filenamePrefix, pointsFor }) {
  if (!curves?.length) {
    ElMessage.warning('请先增加曲线')
    return
  }
  tsChart?.captureFrozenZoom()
  const win = tsChart?.getTimeWindow()
  if (!win) {
    ElMessage.warning('无法获取当前时间窗口')
    return
  }
  const seriesList = curves.map(c => ({
    name: `${c.field} ${c.name}${c.unit ? `(${c.unit})` : ''}`.trim(),
    points: pointsFor ? pointsFor(c) : c.points
  }))
  const { headers, rows } = buildAlignedSeriesTable(seriesList, win)
  if (!rows.length) {
    ElMessage.warning('当前时间窗口内无数据点可导出')
    return
  }
  const stamp = formatCsvDateTime(Date.now()).replace(/[: ]/g, '-').replace(/\./g, '_')
  const prefix = filenamePrefix || 'telemetry-curve'
  exportCsvFile({
    headers,
    rows,
    filename: `${prefix}-${stamp}.csv`
  })
  ElMessage.success(`已导出 ${rows.length} 行（${headers.length - 1} 条曲线）`)
}
