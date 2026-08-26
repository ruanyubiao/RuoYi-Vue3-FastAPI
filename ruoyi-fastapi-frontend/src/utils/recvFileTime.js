/**
 * 从 recv 文件路径解析采集起始时间。
 * 文件名中 ``YYYYMMDD_HHMMSS_mmm``（如 20260824_103104_356）为起始时刻；
 * 第 n 帧数据时间 = 起始 + (n-1) 秒。
 */

const STAMP_RE = /(\d{8})_(\d{6})_(\d{1,3})/

export function parseRecvFileStartMs(path) {
  const name = String(path || '')
    .replace(/\\/g, '/')
    .split('/')
    .pop() || ''
  const m = name.match(STAMP_RE)
  if (!m) return null
  const ymd = m[1]
  const hms = m[2]
  const ms = Number(String(m[3]).padStart(3, '0').slice(0, 3))
  const y = Number(ymd.slice(0, 4))
  const mo = Number(ymd.slice(4, 6)) - 1
  const d = Number(ymd.slice(6, 8))
  const hh = Number(hms.slice(0, 2))
  const mm = Number(hms.slice(2, 4))
  const ss = Number(hms.slice(4, 6))
  const t = new Date(y, mo, d, hh, mm, ss, ms).getTime()
  return Number.isFinite(t) ? t : null
}

/** 与实时表刷新时间同一格式：YYYY-MM-DD HH:mm:ss.mmm */
export function formatTelemetryTs(ms) {
  const t = Number(ms)
  if (!Number.isFinite(t)) return ''
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return ''
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

/** 第 frameIndex 帧（1-based）的数据时间；路径无法解析则返回空串 */
export function fileFrameDataTs(path, frameIndex) {
  const start = parseRecvFileStartMs(path)
  if (start == null) return ''
  const idx = Math.max(1, Number(frameIndex) || 1)
  return formatTelemetryTs(start + (idx - 1) * 1000)
}
