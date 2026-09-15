const DEFAULT_WINDOW_MS = 10 * 60 * 1000
const LIVE_EDGE_MS = 2000

export function clampTimeWindow(start, end, earliest, latest, options = {}) {
  const liveEdgeMs = Number(options.liveEdgeMs) > 0 ? Number(options.liveEdgeMs) : LIVE_EDGE_MS
  const defaultWindowMs = Number(options.defaultWindowMs) > 0 ? Number(options.defaultWindowMs) : DEFAULT_WINDOW_MS
  const last = Number(latest) || 0
  const first = Number(earliest) || 0
  let s = Number(start)
  let e = Number(end)
  if (!Number.isFinite(s) || !Number.isFinite(e)) return { startValue: first, endValue: last || Date.now() }
  if (e > last + liveEdgeMs) e = last
  if (s < first) s = first
  if (e <= s) s = Math.max(first, e - defaultWindowMs)
  return { startValue: s, endValue: e }
}

export function liveFollowWindow(earliest, latest, windowMs, options = {}) {
  const defaultWindowMs = Number(options.defaultWindowMs) > 0 ? Number(options.defaultWindowMs) : DEFAULT_WINDOW_MS
  const end = Number(latest) || Date.now()
  const first = Number(earliest) || 0
  const span = Number(windowMs) > 0 ? Number(windowMs) : defaultWindowMs
  let start = end - span
  if (first && start < first) start = first
  if (end <= start) start = end - defaultWindowMs
  return clampTimeWindow(start, end, first, end, options)
}

export function startPinnedWindow(earliest, latest, windowMs, options = {}) {
  const defaultWindowMs = Number(options.defaultWindowMs) > 0 ? Number(options.defaultWindowMs) : DEFAULT_WINDOW_MS
  const first = Number(earliest) || 0
  const last = Number(latest) || Date.now()
  const span = Number(windowMs) > 0 ? Number(windowMs) : defaultWindowMs
  let start = first
  let end = start + span
  if (end > last) end = last
  if (end <= start) end = start + defaultWindowMs
  return clampTimeWindow(start, end, first, last, options)
}

/** 本轮 setOption 触发的多次 datazoom 都跳过 Y；由调用方在下一拍清掉，避免 flag 粘住。 */
export function createKeepYGuard(scheduleClear) {
  let n = 0
  const clear = typeof scheduleClear === 'function' ? scheduleClear : fn => queueMicrotask(fn)
  return {
    begin() {
      n += 1
      clear(() => {
        n = Math.max(0, n - 1)
      })
    },
    active() {
      return n > 0
    }
  }
}
