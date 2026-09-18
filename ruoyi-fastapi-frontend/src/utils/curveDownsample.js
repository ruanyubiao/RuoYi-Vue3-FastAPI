/**
 * 实时曲线抽稀：按窗口保留峰谷，减少上屏点数。
 *
 * 倍率 N → 窗口 2N 个点，保留最小值、最大值各 1 个（按时间排序）。
 * 谷/峰若落在同一点，或全部等值，只留时间更早的那一个。
 * 末窗不足 2N 个点同样处理；只剩 1 个则原样保留。
 */

export const CURVE_DOWNSAMPLE_RATIOS = [10, 20, 50, 100, 200, 500, 1000]

export function downsampleWindowSize(ratio) {
  const n = Math.floor(Number(ratio) || 0)
  if (n <= 1) return 0
  return n * 2
}

function pointValue(p) {
  const v = Number(Array.isArray(p) ? p[1] : p?.v)
  return Number.isFinite(v) ? v : null
}

function pointTime(p) {
  const t = Number(Array.isArray(p) ? p[0] : p?.t)
  return Number.isFinite(t) ? t : null
}

/** 窗口内取峰谷；等值时留更早的点。 */
export function downsampleWindowMinMax(chunk) {
  if (!Array.isArray(chunk) || !chunk.length) return []
  if (chunk.length === 1) return [chunk[0]]
  let minP = null
  let maxP = null
  for (const p of chunk) {
    const v = pointValue(p)
    const t = pointTime(p)
    if (v == null || t == null) continue
    if (
      minP == null ||
      v < pointValue(minP) ||
      (v === pointValue(minP) && t < pointTime(minP))
    ) {
      minP = p
    }
    if (
      maxP == null ||
      v > pointValue(maxP) ||
      (v === pointValue(maxP) && t < pointTime(maxP))
    ) {
      maxP = p
    }
  }
  if (!minP) return []
  if (!maxP || minP === maxP || pointTime(minP) === pointTime(maxP)) return [minP]
  return pointTime(minP) < pointTime(maxP) ? [minP, maxP] : [maxP, minP]
}

export function downsampleMinMax(points, ratio) {
  const win = downsampleWindowSize(ratio)
  if (!win || !Array.isArray(points) || !points.length) {
    return Array.isArray(points) ? points : []
  }
  if (points.length <= 2) return downsampleWindowMinMax(points)
  const out = []
  for (let i = 0; i < points.length; i += win) {
    const kept = downsampleWindowMinMax(points.slice(i, i + win))
    for (const p of kept) out.push(p)
  }
  return out
}
