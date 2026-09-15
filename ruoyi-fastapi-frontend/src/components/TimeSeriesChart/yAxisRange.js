/**
 * 实时曲线 Y 轴：取整齐刻度，避免每次刷点都改 min/max 导致刻度叠乱、横线上下跳。
 */

/** factor<1 放大，>1 缩小。按钮和滚轮共用，避免手感不一致。 */
export const Y_ZOOM_IN = 0.85
export const Y_ZOOM_OUT = 1.15

function niceInterval(span, ticks) {
  const t = Math.max(2, ticks)
  const raw = span / t
  if (!(raw > 0) || !Number.isFinite(raw)) return 1
  const mag = 10 ** Math.floor(Math.log10(raw))
  const r = raw / mag
  let nice = 10
  if (r <= 1) nice = 1
  else if (r <= 2) nice = 2
  else if (r <= 5) nice = 5
  return nice * mag
}

/** 把 [lo, hi] 扩成整齐 min/max/interval（含边距）。 */
export function niceYRange(lo, hi, options = {}) {
  const a = Number(lo)
  const b = Number(hi)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  let min = Math.min(a, b)
  let max = Math.max(a, b)
  const padRatio = Number(options.padRatio)
  const pad = Number.isFinite(padRatio) ? padRatio : 0.08
  const ticks = Number(options.ticks) > 0 ? Number(options.ticks) : 5
  if (max === min) {
    const p = Math.max(Math.abs(min) * 0.05, 1)
    min -= p
    max += p
  } else {
    const extra = (max - min) * pad
    min -= extra
    max += extra
  }
  const interval = niceInterval(max - min, ticks)
  min = Math.floor(min / interval) * interval
  max = Math.ceil(max / interval) * interval
  if (!(max > min)) max = min + interval
  return { min, max, interval }
}

/** min/max 与 interval 对齐（允许只改一端后出现半格跨度）。 */
export function alignedYInterval(min, max, interval) {
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) return null
  if (!(Number.isFinite(interval) && interval > 0)) return null
  const n = (max - min) / interval
  if (!(n >= 0.5 && n <= 40)) return null
  if (Math.abs(n * 2 - Math.round(n * 2)) > 1e-6) return null
  const half = interval / 2
  const k = min / half
  if (Math.abs(k - Math.round(k)) > 1e-6) return null
  return interval
}

/** 写入 ECharts 的范围：端点必须落在整齐刻度上，避免顶/底出现 2660.00763363 这种被裁成 00763363 的标签。 */
export function displayYRange(range) {
  const min = Number(range?.min)
  const max = Number(range?.max)
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) return null
  if (alignedYInterval(min, max, range?.interval)) {
    return { min, max, interval: range.interval }
  }
  return niceYRange(min, max, { padRatio: 0 })
}

export function formatYTick(value, interval) {
  const v = Number(value)
  if (!Number.isFinite(v)) return ''
  const step = Number(interval)
  if (Number.isFinite(step) && step > 0) {
    const grid = step / 2
    const k = v / grid
    if (Math.abs(k - Math.round(k)) > 1e-5) return ''
    const nice = Math.round(k) * grid
    if (grid >= 1) return String(Math.round(nice))
    const digits = Math.min(6, Math.max(1, Math.ceil(-Math.log10(grid) - 1e-9)))
    return nice.toFixed(digits)
  }
  return String(v)
}

/**
 * 沿 Y 轴平移。direction>0 为上移（max 变小），<0 为下移（max 变大）。
 * 步长 = 相邻刻度间距的一半。
 */
export function panYRange(range, direction) {
  const shown = displayYRange(range)
  const min = Number(shown?.min)
  const max = Number(shown?.max)
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) return range || null
  const dir = Number(direction) > 0 ? 1 : Number(direction) < 0 ? -1 : 0
  if (!dir) return shown
  let interval = Number(shown.interval)
  if (!(interval > 0)) interval = (max - min) / 5
  const step = interval / 2
  return { min: min - dir * step, max: max - dir * step, interval }
}

function halfStep(range) {
  const shown = displayYRange(range)
  const min = Number(shown?.min)
  const max = Number(shown?.max)
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) {
    return { shown: range || null, min, max, interval: 0, step: 0 }
  }
  let interval = Number(shown.interval)
  if (!(interval > 0)) interval = (max - min) / 5
  return { shown, min, max, interval, step: interval / 2 }
}

/** direction>0 放大最大值（max 变大），<0 缩小最大值。 */
export function nudgeYMax(range, direction) {
  const { shown, min, max, interval, step } = halfStep(range)
  const dir = Number(direction) > 0 ? 1 : Number(direction) < 0 ? -1 : 0
  if (!dir || !(step > 0)) return shown
  const nextMax = max + dir * step
  if (!(nextMax > min)) return shown
  return { min, max: nextMax, interval }
}

/** direction>0 最小值变大，<0 最小值变小。 */
export function nudgeYMin(range, direction) {
  const { shown, min, max, interval, step } = halfStep(range)
  const dir = Number(direction) > 0 ? 1 : Number(direction) < 0 ? -1 : 0
  if (!dir || !(step > 0)) return shown
  const nextMin = min + dir * step
  if (!(max > nextMin)) return shown
  return { min: nextMin, max, interval }
}

/** 以 Y 轴中点为中心缩放，factor<1 放大，>1 缩小。 */
export function zoomYCenter(range, factor) {
  const shown = displayYRange(range) || range
  const f = Number(factor)
  if (!Number.isFinite(f) || f <= 0) return shown
  const min = Number(shown?.min)
  const max = Number(shown?.max)
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) return range || null
  const zoomed = zoomYRange(shown, f, (min + max) / 2)
  return settleZoomedYRange(shown, zoomed, f)
}

/** 放大时禁止向外取整回原范围，否则点一次 + 看起来没动。 */
export function settleZoomedYRange(prev, zoomed, factor) {
  const f = Number(factor)
  if (!zoomed) return prev || null
  if (f < 1) {
    const inside = snapYRangeInside(zoomed.min, zoomed.max)
    if (inside && prev && inside.max - inside.min < prev.max - prev.min - 1e-9) return inside
    return shrinkTowardCenter(prev)
  }
  if (f > 1) {
    const out = niceYRange(zoomed.min, zoomed.max, { padRatio: 0 })
    if (out && prev && out.max - out.min > prev.max - prev.min + 1e-9) return out
    return expandTowardEnds(prev)
  }
  return zoomed
}

function snapYRangeInside(lo, hi) {
  const min = Math.min(Number(lo), Number(hi))
  const max = Math.max(Number(lo), Number(hi))
  if (!(max > min)) return null
  const target = max - min
  let best = null
  for (const ticks of [5, 4, 6, 8, 10, 12]) {
    const interval = niceInterval(target, ticks)
    const smin = Math.ceil(min / interval - 1e-12) * interval
    const smax = Math.floor(max / interval + 1e-12) * interval
    if (!(smax > smin)) continue
    const n = (smax - smin) / interval
    if (n < 2 || n > 40) continue
    const span = smax - smin
    if (!best || Math.abs(span - target) < Math.abs(best.max - best.min - target)) {
      best = { min: smin, max: smax, interval }
    }
  }
  return best
}

function halfTick(range) {
  const interval = Number(range?.interval)
  if (interval > 0) return interval / 2
  const span = Number(range?.max) - Number(range?.min)
  return span > 0 ? span / 10 : 1
}

function shrinkTowardCenter(range) {
  const step = halfTick(range)
  const nextMin = Number(range.min) + step
  const nextMax = Number(range.max) - step
  if (!(nextMax > nextMin)) return range
  return { min: nextMin, max: nextMax, interval: range.interval }
}

function expandTowardEnds(range) {
  const step = halfTick(range)
  return { min: Number(range.min) - step, max: Number(range.max) + step, interval: range.interval }
}

function spanLimits(min, max) {
  const mag = Math.max(Math.abs(min), Math.abs(max), 1)
  return { minSpan: mag * 1e-6, maxSpan: mag * 1e4 }
}

/**
 * 滚轮缩放 Y 轴。非法 pivot（例如误把时间戳当 Y）一律回退到中点，并限制最大/最小跨度。
 */
export function zoomYRange(range, factor, pivot) {
  const min = Number(range?.min)
  const max = Number(range?.max)
  if (!(Number.isFinite(min) && Number.isFinite(max) && max > min)) return range || null
  const f = Number(factor)
  if (!Number.isFinite(f) || f <= 0) return range
  const span = max - min
  let p = Number(pivot)
  if (!Number.isFinite(p) || p < min - span || p > max + span) {
    p = (min + max) / 2
  }
  let nextMin = p - (p - min) * f
  let nextMax = p + (max - p) * f
  if (!(nextMax > nextMin) || !Number.isFinite(nextMin) || !Number.isFinite(nextMax)) return range
  const mid = (nextMin + nextMax) / 2
  const { minSpan, maxSpan } = spanLimits(min, max)
  let nextSpan = nextMax - nextMin
  if (nextSpan < minSpan) {
    nextMin = mid - minSpan / 2
    nextMax = mid + minSpan / 2
  } else if (nextSpan > maxSpan) {
    nextMin = mid - maxSpan / 2
    nextMax = mid + maxSpan / 2
  }
  return { min: nextMin, max: nextMax }
}

/** 数据仍在当前轴范围内则保持，越界才重算，横线不会每拍挪动。 */
export function stabilizeYRange(current, dataMin, dataMax, options = {}) {
  const lo = Number(dataMin)
  const hi = Number(dataMax)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return current || null
  if (
    current &&
    Number.isFinite(current.min) &&
    Number.isFinite(current.max) &&
    lo >= current.min &&
    hi <= current.max
  ) {
    return current
  }
  return niceYRange(lo, hi, options)
}
