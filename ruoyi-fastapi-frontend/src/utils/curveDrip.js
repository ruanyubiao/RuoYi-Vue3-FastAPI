/**
 * 实时曲线增量缓存匀速上屏。
 *
 * 新数据入队后按「当前缓存长度 / 一窗拍数」得到每拍条数。
 * 缓存用 head 下标推进，避免 splice(0, n) 每次搬动剩余上千点。
 * sinceT 必须用已拉取末点，不能用已上屏末点。
 */

export const CURVE_POLL_INTERVAL_MS = 300
export const CURVE_DRIP_INTERVAL_MS = 50
/** 比墙钟快过该值视为异常未来点（旧唯一时钟跑飞后的 sinceT） */
export const CURVE_TS_MAX_AHEAD_MS = 5000
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

/** 积压超过 maxLag 的点直接丢掉，上屏跟最新数据沿，避免 X 轴越走越慢。 */
export function dripCatchUpHead(buf, head = 0, maxLagMs = CURVE_POLL_INTERVAL_MS) {
  const h = Math.max(0, Math.floor(Number(head) || 0))
  const last = dripBufferLast(buf, h)
  const lastT = pointTime(last)
  if (lastT == null) return h
  const lag = Number(maxLagMs)
  const cutoff = lastT - (Number.isFinite(lag) && lag > 0 ? lag : CURVE_POLL_INTERVAL_MS)
  let i = h
  const len = Array.isArray(buf) ? buf.length : 0
  while (i < len) {
    const t = pointTime(buf[i])
    if (t == null || t >= cutoff) break
    i += 1
  }
  return i
}

/**
 * 实时上屏：按步长从队头取出，不丢时间段。
 * 5000Hz 积压靠 CURVE_DISPLAY_MAX 和等时间桶上屏，不在这里挖洞。
 */
export function takeLiveDrip(buf, head = 0, options = {}) {
  const h0 = Math.max(0, Math.floor(Number(head) || 0))
  let batch = Math.floor(Number(options.batch) || 0)
  if (batch <= 0) batch = dripBatchSize(dripBufferLength(buf, h0), options)
  return takeDrip(Array.isArray(buf) ? buf : [], batch, h0)
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

/** 水位只跟本次拉取到的最大 t 走，不会退回到已上屏的旧时间；未来水位作废。 */
export function nextFetchCursor(prevCursor, fetchedPoints, now = Date.now()) {
  const prev = sanitizeSinceT(prevCursor, now)
  const last = sanitizeSinceT(lastTimeOf(fetchedPoints), now)
  if (last == null) return prev
  return prev == null ? last : Math.max(prev, last)
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

export function isCurveTimeInFuture(t, now = Date.now()) {
  const n = Number(t)
  return Number.isFinite(n) && n > now + CURVE_TS_MAX_AHEAD_MS
}

/** 未来水位丢弃，否则增量 sinceT 永远大于墙钟新点。 */
export function sanitizeSinceT(t, now = Date.now()) {
  const n = Number(t)
  if (!Number.isFinite(n) || n <= 0) return null
  if (n > now + CURVE_TS_MAX_AHEAD_MS) return null
  return n
}

export function dropFutureCurvePoints(points, now = Date.now()) {
  if (!Array.isArray(points) || !points.length) return Array.isArray(points) ? points : []
  const cap = now + CURVE_TS_MAX_AHEAD_MS
  const kept = points.filter(p => {
    const t = pointTime(p)
    return t != null && t <= cap
  })
  return kept.length === points.length ? points : kept
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

/**
 * 本轮拉取如何进入滴灌缓存。
 * Redis 已空（incoming 为空）时，剩余缓存一次性交给上屏，避免按 1 点/拍空转几分钟。
 */
export function applyLiveFetch(pending, incoming, maxLen) {
  const prev = Array.isArray(pending) ? pending : []
  if (!incoming?.length) {
    return { pending: [], flush: prev }
  }
  return { pending: mergePoints(prev, incoming, maxLen), flush: [] }
}

/** 本条曲线自己的增量 sinceT：已拉水位、已上屏末点、缓存末点取最大。 */
export function incrementalSinceT(curve, now = Date.now()) {
  const cands = [
    Number(curve?.fetchCursorT),
    lastTimeOf(curve?.points),
    lastTimeOf(curve?.pending, curve?.pendingHead),
    lastTimeOf(curve?.pauseCache)
  ]
    .map(t => sanitizeSinceT(t, now))
    .filter(t => t != null)
  return cands.length ? Math.max(...cands) : null
}
