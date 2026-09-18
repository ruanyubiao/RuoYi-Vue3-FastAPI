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
import { nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { displayYRange, formatYTick, niceYRange, nudgeYMax, nudgeYMin, panYRange, settleZoomedYRange, stabilizeYRange, Y_ZOOM_IN, Y_ZOOM_OUT, zoomYCenter, zoomYRange } from './yAxisRange'
import { seriesTimeBounds, visibleYExtent } from './seriesTime'
import { clampTimeWindow, createKeepYGuard, liveFollowWindow, startPinnedWindow } from './xAxisWindow'

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
    zoomY = ref(false),
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
  let plottedSeries = 0
  // 双 nextTick：覆盖 inside+slider 两次 datazoom，以及 ECharts 可能延后到下一拍的事件
  const keepY = createKeepYGuard(fn => nextTick(() => nextTick(fn)))
  let zrWheelHandler = null
  let ignoreDataZoom = 0

  function timeBounds() {
    return seriesTimeBounds(getSeriesPoints())
  }

  function getLatestTime() {
    return timeBounds().latest
  }

  function getEarliestTime() {
    return timeBounds().earliest
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
        showDataShadow: false
      },
      z
    )
  }

  function buildDataZooms(z) {
    return [buildInsideXZoom(z), buildSliderZoom(z)]
  }

  function computeVisibleYExtent() {
    return visibleYExtent(getSeriesPoints(), getTimeWindow())
  }

  function yAxisOption(range) {
    const shown = displayYRange(range)
    const base = {
      type: 'value',
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0
    }
    if (!shown) {
      return { ...base, scale: true, min: null, max: null }
    }
    return {
      ...base,
      scale: false,
      min: shown.min,
      max: shown.max,
      interval: shown.interval,
      axisLabel: {
        hideOverlap: true,
        formatter: val => formatYTick(val, shown.interval)
      }
    }
  }

  function applyYAxisOption(range) {
    if (!chart) return
    chart.setOption({ yAxis: yAxisOption(range) }, { replaceMerge: ['yAxis'] })
  }

  function resolveYAxis({ force = false } = {}) {
    if (yUserLock && yRange) return yAxisOption(yRange)
    const ext = computeVisibleYExtent()
    if (!ext) return yAxisOption(null)
    yRange = force ? niceYRange(ext.min, ext.max) : stabilizeYRange(yRange, ext.min, ext.max)
    return yAxisOption(yRange)
  }

  function fitYAxis() {
    yUserLock = false
    const ext = computeVisibleYExtent()
    yRange = ext ? niceYRange(ext.min, ext.max) : null
    applyYAxisOption(yRange)
  }

  /** direction>0 上移（max 变小），<0 下移（max 变大），步长为相邻刻度间距的一半。 */
  function panYAxis(direction) {
    commitYUserRange(panYRange(ensureYRange(), direction))
  }

  function nudgeYMaxBound(direction) {
    commitYUserRange(nudgeYMax(ensureYRange(), direction))
  }

  function nudgeYMinBound(direction) {
    commitYUserRange(nudgeYMin(ensureYRange(), direction))
  }

  function zoomYAtCenter(factor) {
    commitYUserRange(zoomYCenter(ensureYRange(), factor))
  }

  function ensureYRange() {
    if (!yRange) {
      const ext = computeVisibleYExtent()
      yRange = ext ? niceYRange(ext.min, ext.max) : null
    }
    return yRange
  }

  function commitYUserRange(next) {
    if (!chart || !next) return
    yRange = next
    yUserLock = true
    applyYAxisOption(yRange)
  }

  function applyZoomOption(z, extra = {}) {
    if (!chart) return
    const prevY = yRange
    const patch = {
      ...extra,
      dataZoom: buildDataZooms(z)
    }
    // 范围没变就不要反复写 yAxis，否则刻度会跟着动画叠乱、横线上下跳
    const replaceMerge = ['dataZoom']
    if (!keepY.active()) {
      const yAxis = resolveYAxis()
      if (yRange !== prevY) {
        patch.yAxis = yAxis
        replaceMerge.push('yAxis')
      }
    }
    chart.setOption(patch, { replaceMerge })
  }

  function clampWindow(start, end) {
    const { earliest, latest } = timeBounds()
    return clampTimeWindow(start, end, earliest, latest || Date.now(), {
      liveEdgeMs: liveEdgeThresholdMs,
      defaultWindowMs: defaultViewWindowMs
    })
  }

  function buildLiveFollowZoom() {
    const { earliest, latest } = timeBounds()
    return liveFollowWindow(earliest, latest, viewWindowMs, {
      liveEdgeMs: liveEdgeThresholdMs,
      defaultWindowMs: defaultViewWindowMs
    })
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

  /** 实时跟新：一次 setOption 写 series+窗口，避免每拍 getOption 克隆万点再刷两次。 */
  function paintLiveFrame() {
    if (!chart) return
    if (cropMode.value) {
      updateSeriesOnly()
      return
    }
    ignoreDataZoom += 1
    try {
      keepY.begin()
      const series = getSeries()
      const z = liveFollow ? buildLiveFollowZoom() : frozenZoom || readFrozenZoom()
      if (liveFollow) frozenZoom = z
      const prevY = yRange
      const patch = {
        series,
        dataZoom: buildDataZooms(z || {})
      }
      const replaceMerge = ['series', 'dataZoom']
      if (!yUserLock) {
        const yAxis = resolveYAxis()
        if (yRange !== prevY) {
          patch.yAxis = yAxis
          replaceMerge.push('yAxis')
        }
      }
      chart.setOption(patch, { replaceMerge })
    } finally {
      ignoreDataZoom -= 1
    }
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
    const addedFirst = plottedSeries === 0 && series.length > 0
    plottedSeries = series.length
    if (!series.length) {
      yUserLock = false
      yRange = null
    }
    if (full || !series.length || addedFirst) {
      if (addedFirst) {
        yUserLock = false
        yRange = null
      }
      const z = buildLiveFollowZoom()
      liveFollow = true
      frozenZoom = z
      chart.setOption(
        {
          animation: false,
          tooltip: {
            trigger: 'axis',
            animation: false,
            transitionDuration: 0,
            axisPointer: { type: 'line', animation: false }
          },
          toolbox: { show: false, feature: {} },
          brush: buildBrushOption(),
          grid: { left: 52, right: 10, top: 16, bottom: dataZoomSliderHeight + 36 },
          xAxis: { type: 'time' },
          yAxis: resolveYAxis({ force: addedFirst }),
          dataZoom: buildDataZooms(z),
          series
        },
        { notMerge: true }
      )
      if (addedFirst) fitYAxis()
      if (cropMode.value) nextTick(() => setBrushCursor(true))
      scheduleResize()
      return
    }
    updateSeriesOnly()
    applyViewAfterData()
  }

  function onDataZoom() {
    if (ignoreDataZoom || cropMode.value) return
    const z = readFrozenZoom()
    if (z?.endValue != null) {
      liveFollow = isEndAtLatest(z.endValue)
      if (liveFollow && z.startValue != null) {
        viewWindowMs = Math.max(1000, z.endValue - z.startValue)
      }
    }
    captureFrozenZoom()
    if (keepY.active()) return
    if (!yUserLock) {
      const prevY = yRange
      resolveYAxis()
      if (yRange !== prevY) applyYAxisOption(yRange)
    }
  }

  function resetTimeWindow() {
    exitCropMode({ silent: true })
    liveFollow = true
    viewWindowMs = defaultViewWindowMs
    yUserLock = false
    yRange = null
    frozenZoom = buildLiveFollowZoom()
    render({ full: true })
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
    viewWindowMs = currentWindowMs()
    moveXWindow(buildLiveFollowZoom(), true)
  }

  /** 保持当前窗口宽度，把左端钉到已有数据的最早时间。 */
  function jumpToStart() {
    viewWindowMs = currentWindowMs()
    const { earliest, latest } = timeBounds()
    moveXWindow(
      startPinnedWindow(earliest, latest, viewWindowMs, {
        liveEdgeMs: liveEdgeThresholdMs,
        defaultWindowMs: defaultViewWindowMs
      }),
      false
    )
  }

  /** 只改时间窗口，不重算 Y 轴。 */
  function moveXWindow(z, follow) {
    keepY.begin()
    exitCropMode({ silent: true })
    liveFollow = !!follow
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

  function pixelToYValue(e) {
    const ev = e?.event || e || {}
    const x = e?.zrX ?? ev.zrX ?? ev.offsetX
    const y = e?.zrY ?? ev.zrY ?? ev.offsetY
    if (x == null || y == null) return null
    const data = chart.convertFromPixel({ gridIndex: 0 }, [x, y])
    const v = Array.isArray(data) ? Number(data[1]) : Number(data)
    return Number.isFinite(v) ? v : null
  }

  function onZrMouseWheel(e) {
    if (!zoomY.value || cropMode.value || !chart) return
    const ev = e.event || e
    const delta = e.wheelDelta != null ? e.wheelDelta : ev.deltaY != null ? -ev.deltaY : 0
    if (!delta) return
    if (!yRange) {
      const ext = computeVisibleYExtent()
      yRange = ext ? niceYRange(ext.min, ext.max) : null
    }
    if (!yRange) return
    yUserLock = true
    const prev = displayYRange(yRange) || yRange
    const factor = delta > 0 ? Y_ZOOM_IN : Y_ZOOM_OUT
    const zoomed = zoomYRange(prev, factor, pixelToYValue(e))
    const next = settleZoomedYRange(prev, zoomed, factor)
    if (!next || (next.min === prev.min && next.max === prev.max)) return
    yRange = next
    applyYAxisOption(yRange)
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
    plottedSeries = 0
    yUserLock = false
    yRange = null
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
    paintLiveFrame,
    applyViewAfterData,
    captureFrozenZoom,
    readFrozenZoom,
    resetTimeWindow,
    followLatest,
    jumpToStart,
    refreshZoomBindings,
    fitYAxis,
    panYAxis,
    nudgeYMaxBound,
    nudgeYMinBound,
    zoomYAtCenter,
    toggleCropMode,
    exitCropMode,
    getTimeWindow,
    getLatestTime,
    getEarliestTime,
    getInstance
  }
}
