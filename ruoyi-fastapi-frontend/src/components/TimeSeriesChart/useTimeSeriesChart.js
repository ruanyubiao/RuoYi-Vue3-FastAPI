/**
 * 可复用的「时间轴多曲线」ECharts 组合逻辑：
 * - dataZoom（inside + slider）
 * - 跟最新 / 固定窗口
 * - 拖选截取时间范围
 *
 * 其它页面用法示例：
 *   const chart = useTimeSeriesChart({ chartRef, getSeries, getSeriesPoints, zoomX, zoomY })
 *   onMounted(() => chart.init())
 *   onBeforeUnmount(() => chart.dispose())
 */
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

const DEFAULTS = {
  defaultViewWindowMs: 10 * 60 * 1000,
  dataZoomSliderHeight: 30,
  liveEdgeThresholdMs: 2000,
  minSelectMs: 50
}

/**
 * @param {object} options
 * @param {import('vue').Ref<HTMLElement|null>} options.chartRef
 * @param {() => any[]} options.getSeries  返回 ECharts series
 * @param {() => Array<{ points: Array<[number, any]> }>} options.getSeriesPoints  用于算最早/最晚时间
 * @param {import('vue').Ref<boolean>} [options.zoomX]
 * @param {import('vue').Ref<boolean>} [options.zoomY]
 * @param {number} [options.defaultViewWindowMs]
 * @param {number} [options.dataZoomSliderHeight]
 * @param {number} [options.liveEdgeThresholdMs]
 */
export function useTimeSeriesChart(options) {
  const {
    chartRef,
    getSeries,
    getSeriesPoints,
    zoomX = ref(true),
    zoomY = ref(true),
    defaultViewWindowMs = DEFAULTS.defaultViewWindowMs,
    dataZoomSliderHeight = DEFAULTS.dataZoomSliderHeight,
    liveEdgeThresholdMs = DEFAULTS.liveEdgeThresholdMs
  } = options

  const cropMode = ref(false)

  let chart = null
  let viewWindowMs = defaultViewWindowMs
  let frozenZoom = null
  let liveFollow = true
  let yRange = null
  let yUserLock = false
  let zrWheelHandler = null

  function getLatestTime() {
    let max = 0
    for (const s of getSeriesPoints() || []) {
      for (const p of s.points || []) {
        if (p[0] > max) max = p[0]
      }
    }
    return max
  }

  function getEarliestTime() {
    let min = Infinity
    for (const s of getSeriesPoints() || []) {
      for (const p of s.points || []) {
        if (p[0] < min) min = p[0]
      }
    }
    return Number.isFinite(min) ? min : 0
  }

  function isEndAtLatest(endValue) {
    const latest = getLatestTime() || Date.now()
    return Math.abs(latest - endValue) <= liveEdgeThresholdMs
  }

  function pickZoom(zooms, id, pred) {
    const list = zooms || []
    return list.find(z => z.id === id) || list.find(pred) || null
  }

  function readFrozenZoom() {
    if (!chart) return null
    const opt = chart.getOption()
    const zooms = opt?.dataZoom || []
    const slider = pickZoom(zooms, 'ts-slider-x', z => z.type === 'slider')
    const insideX = pickZoom(
      zooms,
      'ts-inside-x',
      z => z.type === 'inside' && (Array.isArray(z.xAxisIndex) ? z.xAxisIndex.length : z.xAxisIndex != null)
    )
    const pick = slider || insideX
    if (!pick) return null
    return {
      start: pick.start,
      end: pick.end,
      startValue: pick.startValue,
      endValue: pick.endValue
    }
  }

  function captureFrozenZoom() {
    frozenZoom = readFrozenZoom()
  }

  function applyTimeExtent(cfg, z) {
    if (z?.startValue != null && z?.endValue != null) {
      cfg.startValue = z.startValue
      cfg.endValue = z.endValue
    } else if (z?.start != null && z?.end != null) {
      cfg.start = z.start
      cfg.end = z.end
    }
    return cfg
  }

  function buildInsideXZoom(z) {
    const wheelZoom = zoomX.value && !cropMode.value
    const canPan = !cropMode.value
    return applyTimeExtent(
      {
        id: 'ts-inside-x',
        type: 'inside',
        filterMode: 'none',
        xAxisIndex: [0],
        yAxisIndex: [],
        disabled: cropMode.value,
        zoomOnMouseWheel: wheelZoom,
        moveOnMouseWheel: false,
        moveOnMouseMove: canPan
      },
      z
    )
  }

  function buildSliderZoom(z) {
    return applyTimeExtent(
      {
        id: 'ts-slider-x',
        type: 'slider',
        xAxisIndex: [0],
        yAxisIndex: [],
        bottom: 8,
        height: dataZoomSliderHeight,
        brushSelect: false,
        showDetail: true,
        showDataShadow: true
      },
      z
    )
  }

  function buildDataZooms(z) {
    return [buildInsideXZoom(z), buildSliderZoom(z)]
  }

  function computeVisibleYRange() {
    const win = getTimeWindow()
    let lo = Infinity
    let hi = -Infinity
    for (const s of getSeriesPoints() || []) {
      for (const p of s.points || []) {
        const t = Number(Array.isArray(p) ? p[0] : p?.t)
        const v = Number(Array.isArray(p) ? p[1] : p?.v)
        if (!Number.isFinite(v)) continue
        if (win) {
          if (Number.isFinite(win.start) && t < win.start) continue
          if (Number.isFinite(win.end) && t > win.end) continue
        }
        if (v < lo) lo = v
        if (v > hi) hi = v
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
    if (lo === hi) {
      const pad = Math.max(Math.abs(lo) * 0.05, 1)
      return { min: lo - pad, max: hi + pad }
    }
    const pad = (hi - lo) * 0.08
    return { min: lo - pad, max: hi + pad }
  }

  function yAxisOption(range) {
    if (!range) return { type: 'value', scale: true }
    return { type: 'value', scale: true, min: range.min, max: range.max }
  }

  function resolveYAxis() {
    if (yUserLock && yRange) return yAxisOption(yRange)
    yRange = computeVisibleYRange()
    return yAxisOption(yRange)
  }

  function fitYAxis() {
    yUserLock = false
    yRange = computeVisibleYRange()
    if (chart) chart.setOption({ yAxis: yAxisOption(yRange) })
  }

  function applyZoomOption(z, extra = {}) {
    if (!chart) return
    const patch = {
      ...extra,
      dataZoom: buildDataZooms(z),
      yAxis: resolveYAxis()
    }
    chart.setOption(patch, { replaceMerge: ['dataZoom'] })
  }

  function clampWindow(start, end) {
    const earliest = getEarliestTime()
    const latest = getLatestTime() || Date.now()
    let s = start
    let e = end
    if (e > latest + liveEdgeThresholdMs) e = latest
    if (s < earliest) s = earliest
    if (e <= s) s = Math.max(earliest, e - defaultViewWindowMs)
    return { startValue: s, endValue: e }
  }

  function buildLiveFollowZoom() {
    const end = getLatestTime() || Date.now()
    const earliest = getEarliestTime()
    let start = end - viewWindowMs
    if (earliest && start < earliest) start = earliest
    if (end <= start) start = end - defaultViewWindowMs
    return clampWindow(start, end)
  }

  function buildBrushOption() {
    return {
      // 禁止出现 ECharts 自带的矩形/套索等 brush 工具条
      toolbox: [],
      brushLink: 'all',
      xAxisIndex: 0,
      brushType: 'lineX',
      brushMode: 'single',
      transformable: false,
      throttleType: 'debounce',
      throttleDelay: 0,
      removeOnClick: true,
      brushStyle: {
        borderWidth: 1,
        color: 'rgba(64, 158, 255, 0.18)',
        borderColor: '#409eff'
      },
      outOfBrush: { colorAlpha: 0.15 }
    }
  }

  function restoreViewState(z) {
    applyZoomOption(z)
  }

  function updateSeriesOnly() {
    if (!chart) return
    chart.setOption({ series: getSeries() }, { replaceMerge: ['series'], lazyUpdate: true })
  }

  function applyViewAfterData() {
    if (!chart || cropMode.value) return
    if (liveFollow) {
      const z = buildLiveFollowZoom()
      frozenZoom = z
      applyZoomOption(z)
    } else {
      restoreViewState(frozenZoom || readFrozenZoom())
    }
  }

  function applyTimeWindow(startMs, endMs) {
    let start = Math.min(startMs, endMs)
    let end = Math.max(startMs, endMs)
    if (!(end > start)) {
      ElMessage.warning('请拖选一段有效时间范围')
      return false
    }
    if (end - start < DEFAULTS.minSelectMs) {
      ElMessage.warning('选取范围过短，请重新拖选')
      return false
    }
    const clamped = clampWindow(start, end)
    liveFollow = false
    viewWindowMs = Math.max(1000, clamped.endValue - clamped.startValue)
    frozenZoom = { ...clamped }
    applyZoomOption(frozenZoom)
    return true
  }

  function clearBrushAreas() {
    if (!chart) return
    chart.dispatchAction({ type: 'brush', areas: [] })
  }

  function setBrushCursor(enabled) {
    if (!chart) return
    chart.dispatchAction({
      type: 'takeGlobalCursor',
      key: 'brush',
      brushOption: enabled ? { brushType: 'lineX' } : { brushType: false }
    })
  }

  function exitCropMode({ silent = false } = {}) {
    if (!cropMode.value && silent) return
    cropMode.value = false
    clearBrushAreas()
    setBrushCursor(false)
    applyZoomOption(frozenZoom || readFrozenZoom())
  }

  function toggleCropMode({ hasSeries = true } = {}) {
    if (!hasSeries || !chart) return
    if (cropMode.value) {
      exitCropMode()
      return
    }
    cropMode.value = true
    const z = frozenZoom || readFrozenZoom()
    applyZoomOption(z, {
      toolbox: { show: false, feature: {} },
      brush: buildBrushOption()
    })
    nextTick(() => {
      setBrushCursor(true)
      ElMessage.info('截取模式：按住左键拖选时间范围，松开后完成')
    })
  }

  function onBrushEnd(params) {
    if (!cropMode.value) return
    const area = params?.areas?.[0]
    if (!area) {
      exitCropMode()
      return
    }
    let t1
    let t2
    if (Array.isArray(area.coordRange) && area.coordRange.length >= 2) {
      t1 = Number(area.coordRange[0])
      t2 = Number(area.coordRange[1])
    } else if (Array.isArray(area.range) && area.range.length >= 2 && chart) {
      const p1 = chart.convertFromPixel({ xAxisIndex: 0 }, area.range[0])
      const p2 = chart.convertFromPixel({ xAxisIndex: 0 }, area.range[1])
      t1 = Number(p1)
      t2 = Number(p2)
    }
    clearBrushAreas()
    if (!Number.isFinite(t1) || !Number.isFinite(t2)) {
      exitCropMode()
      return
    }
    const ok = applyTimeWindow(t1, t2)
    cropMode.value = false
    setBrushCursor(false)
    applyZoomOption(frozenZoom || readFrozenZoom())
    if (ok) ElMessage.success('已截取到选定时间范围')
  }

  function scheduleResize() {
    nextTick(() => {
      chart?.resize()
      requestAnimationFrame(() => chart?.resize())
    })
  }

  function render({ full = false } = {}) {
    if (!chart) return
    const series = getSeries()
    if (full || !series.length) {
      const z = buildLiveFollowZoom()
      liveFollow = true
      frozenZoom = z
      chart.setOption(
        {
          tooltip: { trigger: 'axis' },
          toolbox: { show: false, feature: {} },
          brush: buildBrushOption(),
          grid: { left: 55, right: 20, top: 16, bottom: dataZoomSliderHeight + 36 },
          xAxis: { type: 'time' },
          yAxis: resolveYAxis(),
          dataZoom: buildDataZooms(z),
          series
        },
        { notMerge: true }
      )
      if (cropMode.value) nextTick(() => setBrushCursor(true))
      scheduleResize()
      return
    }
    updateSeriesOnly()
    applyViewAfterData()
  }

  function onDataZoom() {
    if (cropMode.value) return
    const z = readFrozenZoom()
    if (z?.endValue != null) {
      liveFollow = isEndAtLatest(z.endValue)
      if (liveFollow && z.startValue != null) {
        viewWindowMs = Math.max(1000, z.endValue - z.startValue)
      }
    }
    captureFrozenZoom()
    if (!yUserLock) {
      yRange = computeVisibleYRange()
      if (chart) chart.setOption({ yAxis: yAxisOption(yRange) })
    }
  }

  function resetTimeWindow() {
    exitCropMode({ silent: true })
    liveFollow = true
    viewWindowMs = defaultViewWindowMs
    const z = buildLiveFollowZoom()
    frozenZoom = z
    yUserLock = false
    applyZoomOption(z)
    render()
  }

  function currentWindowMs() {
    const z = frozenZoom || readFrozenZoom()
    if (z?.startValue != null && z?.endValue != null) {
      const w = Number(z.endValue) - Number(z.startValue)
      if (Number.isFinite(w) && w > 0) return Math.max(1000, w)
    }
    return viewWindowMs
  }

  function followLatest() {
    exitCropMode({ silent: true })
    viewWindowMs = currentWindowMs()
    liveFollow = true
    yUserLock = false
    const z = buildLiveFollowZoom()
    frozenZoom = z
    applyZoomOption(z)
  }

  function refreshZoomBindings() {
    captureFrozenZoom()
    applyZoomOption(frozenZoom || readFrozenZoom() || {})
  }

  /** 当前底部时间轴窗口（供导出等） */
  function getTimeWindow() {
    const z = frozenZoom || readFrozenZoom()
    let start = z?.startValue
    let end = z?.endValue
    if (start == null || end == null) {
      start = getEarliestTime()
      end = getLatestTime()
    }
    start = Number(start)
    end = Number(end)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null
    return { start, end }
  }

  function onZrMouseWheel(e) {
    if (!zoomY.value || cropMode.value || !chart) return
    const ev = e.event || e
    const delta = e.wheelDelta != null ? e.wheelDelta : ev.deltaY != null ? -ev.deltaY : 0
    if (!delta) return
    if (!yRange) yRange = computeVisibleYRange()
    if (!yRange) return
    yUserLock = true
    const factor = delta > 0 ? 0.85 : 1.18
    let { min, max } = yRange
    let pivot = (min + max) / 2
    const offsetY = ev.offsetY ?? ev.zrY
    if (offsetY != null) {
      const y = chart.convertFromPixel({ yAxisIndex: 0 }, offsetY)
      if (Number.isFinite(y)) pivot = y
    }
    min = pivot - (pivot - min) * factor
    max = pivot + (max - pivot) * factor
    if (!(max > min)) return
    yRange = { min, max }
    chart.setOption({ yAxis: yAxisOption(yRange) })
    if (!zoomX.value) {
      e.stop?.()
      ev.preventDefault?.()
    }
  }

  function init() {
    if (!chartRef.value || chart) return
    chart = echarts.init(chartRef.value)
    chart.on('datazoom', onDataZoom)
    chart.on('brushEnd', onBrushEnd)
    zrWheelHandler = onZrMouseWheel
    chart.getZr().on('mousewheel', zrWheelHandler)
    render({ full: true })
  }

  function dispose() {
    exitCropMode({ silent: true })
    if (chart && zrWheelHandler) {
      try {
        chart.getZr().off('mousewheel', zrWheelHandler)
      } catch {
        /* ignore */
      }
    }
    zrWheelHandler = null
    chart?.dispose()
    chart = null
  }

  function resize() {
    chart?.resize()
  }

  function getInstance() {
    return chart
  }

  return {
    cropMode,
    init,
    dispose,
    resize,
    scheduleResize,
    render,
    updateSeriesOnly,
    applyViewAfterData,
    captureFrozenZoom,
    readFrozenZoom,
    resetTimeWindow,
    followLatest,
    refreshZoomBindings,
    fitYAxis,
    toggleCropMode,
    exitCropMode,
    getTimeWindow,
    getLatestTime,
    getEarliestTime,
    getInstance
  }
}
