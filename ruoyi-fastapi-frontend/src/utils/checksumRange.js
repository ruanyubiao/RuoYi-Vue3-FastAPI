/**
 * 校验区间索引：含两端，支持负索引；合法范围 [-len, len-1]，不能等于 len。
 */

export function resolveIndex(index, len) {
  const n = Number(index)
  if (!Number.isInteger(n) || !Number.isFinite(n)) return null
  if (len <= 0) return null
  if (n >= len || n < -len) return null
  return n < 0 ? n + len : n
}

/** 含两端的闭区间。非法时返回 null。 */
export function resolveRange(start, end, len) {
  const a = resolveIndex(start, len)
  const b = resolveIndex(end, len)
  if (a == null || b == null) return null
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  return { lo, hi }
}

export function sliceBytes(bytes, start, end) {
  const range = resolveRange(start, end, bytes.length)
  if (!range) return null
  return bytes.subarray(range.lo, range.hi + 1)
}

export function indexBounds(len) {
  // 还没有字节时也必须 min <= max，否则数字框会在两端之间来回改值，卡死整页。
  if (len <= 0) return { min: -1, max: 0 }
  return { min: -len, max: len - 1 }
}
