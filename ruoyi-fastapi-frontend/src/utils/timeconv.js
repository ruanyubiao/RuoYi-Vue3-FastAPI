/**
 * 调试-时间转换：it-tools 日期格式表、日期字符串解析，
 * 以及协议纪元 + 周 / 周内秒 / 毫秒 ↔ Unix 毫秒。
 *
 * 协议字段：周按 u32，周内秒 0..604800，毫秒 0..999；HEX 先按端序解释，
 * 不足 4 字节时对字节左补 00。纯前端计算，不访问后端。
 */

export const U32_MAX = 0xffffffff
export const WEEK_SECONDS = 604800
export const MAX_DATE_MS = 8640000000000000
/** hexChars：规范化显示位数（周 4 字节 / 周内秒 3 字节 / 毫秒 2 字节）；0 仍显示 `00`。 */
export const PROTOCOL_FIELD_LIMITS = {
  week: { label: '周', max: U32_MAX, hexChars: 8 },
  sow: { label: '周内秒', max: WEEK_SECONDS, hexChars: 6 },
  ms: { label: '毫秒', max: 999, hexChars: 4 }
}
export const PROTOCOL_FIELD_NAMES = ['week', 'sow', 'ms']
export const PROTOCOL_FORMATS = [
  { id: 'dec', label: '整数' },
  { id: 'be', label: 'HEX 大端' },
  { id: 'le', label: 'HEX 小端' }
]

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function pad(value, width = 2) {
  return String(value).padStart(width, '0')
}

function normalizeFormat(format) {
  return PROTOCOL_FORMATS.some(item => item.id === format) ? format : 'dec'
}

function assertU32(value, label) {
  if (!Number.isInteger(value) || value < 0 || value > U32_MAX) {
    throw new Error(`${label}范围是 0 ~ ${U32_MAX}`)
  }
}

/** 十进制整数 / 4 字节 HEX（可带空格）→ u32。空与 0 都表示 0。 */
export function parseProtocolValue(text, format = 'dec', max = U32_MAX, label = '数值') {
  const mode = normalizeFormat(format)
  let value
  if (mode === 'dec') {
    const raw = String(text ?? '').trim()
    if (!raw) {
      value = 0
    } else if (!/^\d+$/.test(raw)) {
      throw new Error(`${label}只能输入非负整数`)
    } else {
      const big = BigInt(raw)
      if (big > BigInt(U32_MAX)) throw new Error(`${label}范围是 0 ~ ${max}`)
      value = Number(big)
    }
  } else {
    const raw = String(text ?? '').replace(/\s+/g, '')
    if (raw && !/^[0-9a-fA-F]+$/.test(raw)) {
      throw new Error(`${label}只能输入 HEX`)
    }
    if (raw.length > 8) {
      throw new Error(`${label} HEX 最多 8 位（4 字节）`)
    }
    if (!raw || /^0+$/.test(raw)) {
      value = 0
    } else {
      const byteHex = raw.length % 2 ? `0${raw}` : raw
      const bytes = byteHex.match(/../g) || []
      const ordered = mode === 'le' ? [...bytes].reverse() : bytes
      value = Number.parseInt(ordered.join('').padStart(8, '0'), 16)
    }
  }
  if (!Number.isInteger(value) || value < 0 || value > max) {
    throw new Error(`${label}范围是 0 ~ ${max}`)
  }
  return value
}

/**
 * u32 → 显示文本。
 * 0 在 HEX 下固定 `00`；非零按 hexChars（默认 8，须为偶数）左补零后按端序排列。
 */
export function formatProtocolValue(value, format = 'dec', hexChars = 8) {
  assertU32(value, '数值')
  const mode = normalizeFormat(format)
  if (mode === 'dec') return String(value)
  if (value === 0) return '00'
  const width = Number.isInteger(hexChars) && hexChars >= 2 && hexChars % 2 === 0 ? hexChars : 8
  const be = value.toString(16).toUpperCase().padStart(width, '0')
  if (mode === 'be') return be
  return (be.match(/../g) || []).reverse().join('')
}

/** 协议纪元 + 周 + 周内秒 + 毫秒 → Unix 毫秒；超范围抛 Error。 */
export function protocolToUnixMs({ epochUtcSec, week = 0, sow = 0, ms = 0 }) {
  const epoch = Number(epochUtcSec)
  if (!Number.isSafeInteger(epoch) || epoch < 0) {
    throw new Error('协议纪元无效')
  }
  assertU32(week, '周')
  if (!Number.isInteger(sow) || sow < 0 || sow > WEEK_SECONDS) {
    throw new Error(`周内秒范围是 0 ~ ${WEEK_SECONDS}`)
  }
  if (!Number.isInteger(ms) || ms < 0 || ms > 999) {
    throw new Error('毫秒范围是 0 ~ 999')
  }
  const total = (BigInt(epoch) + BigInt(week) * BigInt(WEEK_SECONDS) + BigInt(sow)) * 1000n + BigInt(ms)
  if (total < BigInt(-MAX_DATE_MS) || total > BigInt(MAX_DATE_MS)) {
    throw new Error('计算结果超出可表示的日期范围')
  }
  return Number(total)
}

function localDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function localTime(date) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function localMs(date) {
  return String(date.getMilliseconds()).padStart(3, '0')
}

function timezoneOffset(date) {
  const minutes = -date.getTimezoneOffset()
  if (minutes === 0) return 'Z'
  const sign = minutes > 0 ? '+' : '-'
  const abs = Math.abs(minutes)
  return `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

/** ISO 8601 本地时间，含毫秒与时区偏移。 */
function iso8601Local(date) {
  return `${localDate(date)}T${localTime(date)}.${localMs(date)}${timezoneOffset(date)}`
}

/** ISO 9075：本地日期时间，含毫秒，无时区标记。 */
function iso9075(date) {
  return `${localDate(date)} ${localTime(date)}.${localMs(date)}`
}

function rfc7231(date) {
  return (
    `${DAY_NAMES[date.getUTCDay()]}, ${pad(date.getUTCDate())} ${MONTH_NAMES[date.getUTCMonth()]} ` +
    `${date.getUTCFullYear()} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:` +
    `${pad(date.getUTCSeconds())} GMT`
  )
}

/** 与需求表一致的 10 行（含备注）；不含 Mongo ObjectID / Excel date。 */
export const DATE_FORMATS = [
  {
    id: 'js-local',
    label: 'JS 本地日期时间',
    note: 'Date.toString()，按本地时区显示',
    format: date => date.toString()
  },
  {
    id: 'js-localized',
    label: 'JS 本地化日期时间',
    note: 'Date.toLocaleString()，受系统区域和语言设置影响',
    format: date => date.toLocaleString()
  },
  {
    id: 'iso8601-utc',
    label: 'ISO 8601（UTC）',
    note: 'Date.toISOString()，使用 UTC，Z 表示 UTC',
    format: date => date.toISOString()
  },
  {
    id: 'iso8601',
    label: 'ISO 8601',
    note: '国际标准日期时间格式，可包含时区偏移',
    format: iso8601Local
  },
  {
    id: 'iso9075',
    label: 'ISO 9075',
    note: 'SQL 常见日期时间表示形式，不包含时区标记',
    format: iso9075
  },
  {
    id: 'rfc3339',
    label: 'RFC 3339',
    note: '互联网日期时间规范，支持时区偏移和小数秒',
    format: iso8601Local
  },
  {
    id: 'rfc7231',
    label: 'RFC 7231',
    note: 'HTTP 日期格式，使用 GMT，精度为秒',
    format: rfc7231
  },
  {
    id: 'utc',
    label: 'UTC 日期时间',
    note: 'Date.toUTCString()，以 UTC 格式显示',
    format: date => date.toUTCString()
  },
  {
    id: 'unix',
    label: 'Unix 时间戳（秒）',
    note: '从 Unix 纪元起算的秒数，通常为 10 位',
    format: date => String(Math.floor(date.getTime() / 1000))
  },
  {
    id: 'unix-ms',
    label: 'Unix 时间戳（毫秒）',
    note: '从 Unix 纪元起算的毫秒数，通常为 13 位',
    format: date => String(date.getTime())
  }
]

/** Date → 10 行格式结果（时间格式 / 时间格式化显示 / 备注）。 */
export function dateFormatRows(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return []
  return DATE_FORMATS.map(item => ({
    label: item.label,
    value: item.format(date),
    note: item.note
  }))
}

/**
 * 日期字符串 → Date。
 * 手输纯数字：去掉符号后长度 <= 10 为秒，否则为毫秒。
 * options.unit === 'ms' 时按毫秒，不再乘 1000（计算按钮写入的结果）。
 * 空字符串返回 date=null。
 */
export function parseDateInput(text, options = {}) {
  const raw = String(text ?? '').trim()
  if (!raw) return { date: null }
  let ms
  if (/^[+-]?\d+$/.test(raw)) {
    let value
    try {
      value = BigInt(raw)
    } catch {
      return { error: '时间戳格式不正确' }
    }
    const abs = value < 0n ? -value : value
    const digits = abs.toString().length
    const asSeconds = options.unit !== 'ms' && digits <= 10
    const unitMs = asSeconds ? 1000n : 1n
    ms = value * unitMs
    if (ms < BigInt(-MAX_DATE_MS) || ms > BigInt(MAX_DATE_MS)) {
      return { error: '时间戳超出可表示的日期范围' }
    }
    ms = Number(ms)
  } else {
    ms = Date.parse(raw)
    if (Number.isNaN(ms)) return { error: '无法解析日期字符串' }
  }
  if (!Number.isSafeInteger(ms)) return { error: '时间戳超出可表示范围' }
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return { error: '无法解析日期字符串' }
  return { date }
}
