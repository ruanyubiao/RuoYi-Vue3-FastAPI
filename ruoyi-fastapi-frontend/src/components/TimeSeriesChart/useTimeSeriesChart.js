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

  function readFrozenZoom() {
    if (!chart) return null
    const opt = chart.getOption()
    const zooms = opt?.dataZoom || []
    const slider = zooms.find(z => z.type === 'slider')
    const inside = zooms.find(z => z.type === 'inside')
    const pick = slider || inside
    if (!pick) return null
    const z = {
      start: pick.start,
      end: pick.end,
      startValue: pick.startValue,
      endValue: pick.endValue
    }
    const yAxis = opt.yAxis?.[0]
    if (yAxis?.min != null && yAxis.min !== 'dataMin') z.yMin = yAxis.min
    if (yAxis?.max != null && yAxis.max !== 'dataMax') z.yMax = yAxis.max
    return z
  }

  function captureFrozenZoom() {
    frozenZoom = readFrozenZoom()
  }

  function buildInsideZoom(z) {
    const cfg = {
      type: 'inside',
      filterMode: 'none',
      disabled: cropMode.value,
      xAxisIndex: zoomX.value && !cropMode.value ? [0] : [],
      yAxisIndex: zoomY.value && !cropMode.value ? [0] : []
    }
    if (z?.startValue != null && z?.endValue != null) {
      cfg.startValue = z.startValue
      cfg.endValue = z.endValue
    } else if (z?.start != null && z?.end != null) {
      cfg.start = z.start
      cfg.end = z.end
    }
    return cfg
  }

  function buildSliderZoom(z) {
    const cfg = {
      type: 'slider',
      xAxisIndex: [0],
      bottom: 8,
      height: dataZoomSliderHeight,
      brushSelect: false,
      showDetail: true,
      showDataShadow: true
    }
    if (z?.startValue != null && z?.endValue != null) {
      cfg.startValue = z.startValue
      cfg.endValue = z.endValue
    } else if (z?.start != null && z?.end != null) {
      cfg.start = z.start
      cfg.end = z.end
    }
    return cfg
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
    if (!chart || !z) return
    const patch = {
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
    }
    if (z.yMin != null || z.yMax != null) {
      patch.yAxis = { scale: true, min: z.yMin, max: z.yMax }
    }
    chart.setOption(patch)
  }

  function updateSeriesOnly() {
    if (!chart) return
    const patch = { series: getSeries() }
    const z = frozenZoom || readFrozenZoom()
    if (z && (z.yMin != null || z.yMax != null)) {
      patch.yAxis = { scale: true, min: z.yMin, max: z.yMax }
    }
    chart.setOption(patch, { replaceMerge: ['series'], lazyUpdate: true })
  }

  function applyViewAfterData() {
    if (!chart || cropMode.value) return
    if (liveFollow) {
      const z = buildLiveFollowZoom()
      frozenZoom = z
      chart.setOption({
        dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
      })
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
    if (chart) {
      chart.setOption({
        dataZoom: [buildInsideZoom(frozenZoom), buildSliderZoom(frozenZoom)]
      })
    }
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
    const z = frozenZoom || readFrozenZoom()
    if (chart && z) {
      chart.setOption({
        dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
      })
    }
  }

  function toggleCropMode({ hasSeries = true } = {}) {
    if (!hasSeries || !chart) return
    if (cropMode.value) {
      exitCropMode()
      return
    }
    cropMode.value = true
    const z = frozenZoom || readFrozenZoom()
    chart.setOption({
      toolbox: { show: false, feature: {} },
      brush: buildBrushOption(),
      dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
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
    const z = frozenZoom || readFrozenZoom()
    if (chart && z) {
      chart.setOption({
        dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
      })
    }
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
          // 关闭顶部工具箱，避免 brush 自动挂出「矩形选择」等图标
          toolbox: { show: false, feature: {} },
          brush: buildBrushOption(),
          grid: { left: 55, right: 20, top: 16, bottom: dataZoomSliderHeight + 36 },
          xAxis: { type: 'time' },
          yAxis: { type: 'value', scale: true },
          dataZoom: [buildInsideZoom(z), buildSliderZoom(z)],
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
  }

  function resetTimeWindow() {
    exitCropMode({ silent: true })
    liveFollow = true
    viewWindowMs = defaultViewWindowMs
    const z = buildLiveFollowZoom()
    frozenZoom = z
    if (chart) {
      chart.setOption({
        dataZoom: [buildInsideZoom(z), buildSliderZoom(z)],
        yAxis: { scale: true }
      })
    }
    render()
  }

  function refreshZoomBindings() {
    captureFrozenZoom()
    const z = frozenZoom || readFrozenZoom()
    if (chart && z) {
      chart.setOption({
        dataZoom: [buildInsideZoom(z), buildSliderZoom(z)]
      })
    }
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

  function init() {
    if (!chartRef.value || chart) return
    chart = echarts.init(chartRef.value)
    chart.on('datazoom', onDataZoom)
    chart.on('brushEnd', onBrushEnd)
    render({ full: true })
  }

  function dispose() {
    exitCropMode({ silent: true })
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
    refreshZoomBindings,
    toggleCropMode,
    exitCropMode,
    getTimeWindow,
    getLatestTime,
    getEarliestTime,
    getInstance
  }
}
