/** 点列按时间升序时，首末即最早/最晚，不必扫全部点。 */

function pointTime(p) {
  const t = Number(Array.isArray(p) ? p[0] : p?.t)
  return Number.isFinite(t) ? t : null
}

function pointValue(p) {
  const v = Number(Array.isArray(p) ? p[1] : p?.v)
  return Number.isFinite(v) ? v : null
}

function isTimeSorted(pts) {
  if (!pts.length) return true
  const a = pointTime(pts[0])
  const b = pointTime(pts[pts.length - 1])
  if (a == null || b == null) return false
  return a <= b
}

function scanTimeBounds(pts) {
  let min = Infinity
  let max = -Infinity
  for (const p of pts) {
    const t = pointTime(p)
    if (t == null) continue
    if (t < min) min = t
    if (t > max) max = t
  }
  return { min, max }
}

/** 多条曲线的最早/最晚时间。空数据 earliest/latest 为 0。 */
export function seriesTimeBounds(seriesList) {
  let min = Infinity
  let max = -Infinity
  for (const s of seriesList || []) {
    const pts = s.points || []
    if (!pts.length) continue
    const span = isTimeSorted(pts) ? { min: pointTime(pts[0]), max: pointTime(pts[pts.length - 1]) } : scanTimeBounds(pts)
    if (span.min != null && span.min < min) min = span.min
    if (span.max != null && span.max > max) max = span.max
  }
  return {
    earliest: Number.isFinite(min) ? min : 0,
    latest: Number.isFinite(max) ? max : 0
  }
}

function lowerBound(pts, t) {
  let lo = 0
  let hi = pts.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    const tm = pointTime(pts[mid])
    if (tm != null && tm < t) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** 当前时间窗口内的 Y 最小/最大。无有效点返回 null。 */
export function visibleYExtent(seriesList, win) {
  const start = win?.start
  const end = win?.end
  const hasStart = Number.isFinite(start)
  const hasEnd = Number.isFinite(end)
  let lo = Infinity
  let hi = -Infinity
  for (const s of seriesList || []) {
    const pts = s.points || []
    if (!pts.length) continue
    let i = 0
    let n = pts.length
    if (isTimeSorted(pts) && (hasStart || hasEnd)) {
      if (hasStart) i = lowerBound(pts, start)
      if (hasEnd) {
        let j = lowerBound(pts, end)
        while (j < pts.length && pointTime(pts[j]) === end) j++
        n = j
      }
    }
    for (; i < n; i++) {
      const p = pts[i]
      const t = pointTime(p)
      const v = pointValue(p)
      if (v == null) continue
      if (!isTimeSorted(pts) || !(hasStart || hasEnd)) {
        if (hasStart && t != null && t < start) continue
        if (hasEnd && t != null && t > end) continue
      }
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
  return { min: lo, max: hi }
}
