/**
 * 实时曲线增量缓存匀速上屏。
 *
 * 新数据入队后按「当前缓存长度 / 一窗拍数」得到每拍条数。
 * 缓存用 head 下标推进，避免 splice(0, n) 每次搬动剩余上千点。
 * sinceT 必须用已拉取末点，不能用已上屏末点。
 */

export const CURVE_POLL_INTERVAL_MS = 400
export const CURVE_DRIP_INTERVAL_MS = 50
/** head 超过该值才 compact，避免每拍复制剩余数组 */
const DRIP_COMPACT_HEAD = 256

export function dripTicksPerWindow(
  windowMs = CURVE_POLL_INTERVAL_MS,
  intervalMs = CURVE_DRIP_INTERVAL_MS
) {
  const w = Number(windowMs) || CURVE_POLL_INTERVAL_MS
  const i = Number(intervalMs) || CURVE_DRIP_INTERVAL_MS
  return Math.max(1, Math.ceil(w / i))
}

export function dripBatchSize(cacheLen, options = {}) {
  const n = Math.max(0, Math.floor(Number(cacheLen) || 0))
  if (n <= 0) return 0
  const ticks = dripTicksPerWindow(options.windowMs, options.intervalMs)
  return Math.min(n, Math.max(1, Math.ceil(n / ticks)))
}

export function dripBufferLength(buf, head = 0) {
  if (!Array.isArray(buf) || !buf.length) return 0
  const h = Math.max(0, Math.floor(Number(head) || 0))
  return Math.max(0, buf.length - h)
}

export function dripBufferLast(buf, head = 0) {
  if (!dripBufferLength(buf, head)) return null
  return buf[buf.length - 1]
}

export function compactDripBuffer(buf, head = 0) {
  if (!Array.isArray(buf) || !buf.length) return { buf: [], head: 0 }
  const h = Math.max(0, Math.floor(Number(head) || 0))
  if (h <= 0) return { buf, head: 0 }
  if (h >= buf.length) return { buf: [], head: 0 }
  if (h < DRIP_COMPACT_HEAD) return { buf, head: h }
  return { buf: buf.slice(h), head: 0 }
}

/** 只复制本拍切出的点；剩余段用 head 跳过。 */
export function takeDrip(buf, count, head = 0) {
  const h = Math.max(0, Math.floor(Number(head) || 0))
  const n = Math.min(dripBufferLength(buf, h), Math.max(0, Math.floor(Number(count) || 0)))
  if (n <= 0) return { chunk: [], buf: Array.isArray(buf) ? buf : [], head: h }
  const chunk = buf.slice(h, h + n)
  const next = compactDripBuffer(buf, h + n)
  return { chunk, buf: next.buf, head: next.head }
}

function pointTime(p) {
  const t = Number(Array.isArray(p) ? p[0] : p?.t)
  return Number.isFinite(t) ? t : null
}

/** 水位只跟本次拉取到的最大 t 走，不会退回到已上屏的旧时间。 */
export function nextFetchCursor(prevCursor, fetchedPoints) {
  const prev = Number(prevCursor)
  const prevOk = Number.isFinite(prev) ? prev : null
  const last = lastTimeOf(fetchedPoints)
  if (last == null) return prevOk
  return prevOk == null ? last : Math.max(prevOk, last)
}

function lastTimeOf(points, head = 0) {
  if (!Array.isArray(points) || !points.length) return null
  const h = Math.max(0, Math.floor(Number(head) || 0))
  let max = null
  for (let i = h; i < points.length; i++) {
    const t = pointTime(points[i])
    if (t != null && (max == null || t > max)) max = t
  }
  return max
}

/** 已发出的 sinceT 与本地水位取最大，避免并发请求把水位打回去。 */
export function reserveSinceT(prevSent, computed) {
  const cands = [prevSent, computed]
    .map(Number)
    .filter(t => Number.isFinite(t) && t > 0)
  return cands.length ? Math.max(...cands) : null
}

/**
 * 合并点列。增量点若都晚于已有末点，只做 concat/截尾，避免每拍 Map+sort 一万点。
 */
export function mergePoints(existing, incoming, maxLen) {
  if (!incoming?.length) return Array.isArray(existing) ? existing : []
  const cap = Math.max(1, Math.floor(Number(maxLen) || incoming.length))
  const prev = Array.isArray(existing) ? existing : []
  if (!prev.length) {
    return incoming.length > cap ? incoming.slice(-cap) : incoming.slice()
  }
  const lastT = Number(prev[prev.length - 1]?.[0])
  const firstIn = Number(incoming[0]?.[0])
  if (Number.isFinite(lastT) && Number.isFinite(firstIn) && firstIn > lastT) {
    const total = prev.length + incoming.length
    if (total <= cap) return prev.concat(incoming)
    const keep = cap - incoming.length
    if (keep <= 0) return incoming.slice(-cap)
    return prev.slice(-keep).concat(incoming)
  }
  const map = new Map()
  for (const p of prev) map.set(p[0], p[1])
  for (const p of incoming) map.set(p[0], p[1])
  let merged = Array.from(map.entries()).sort((a, b) => a[0] - b[0])
  if (merged.length > cap) merged = merged.slice(-cap)
  return merged
}

/** 本条曲线自己的增量 sinceT：已拉水位、已上屏末点、缓存末点取最大。 */
export function incrementalSinceT(curve) {
  const cands = [
    Number(curve?.fetchCursorT),
    lastTimeOf(curve?.points),
    lastTimeOf(curve?.pending, curve?.pendingHead),
    lastTimeOf(curve?.pauseCache)
  ].filter(t => Number.isFinite(t) && t > 0)
  return cands.length ? Math.max(...cands) : null
}
