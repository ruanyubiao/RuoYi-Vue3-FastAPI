import { getDeviceSnapshot } from '@/api/payload/device'

/** 连接状态快照（串口/CAN/UDP）浏览器缓存，切换页面可复用，带有效期 */
const SNAPSHOT_KEY = 'payload:deviceSnapshot:v1'
/** 快照默认有效期 30s（列表/已开连接，适合跨页瞬间打开弹窗） */
export const SNAPSHOT_TTL_MS = 30_000

const ACTIVE_KEYS = {
  can: 'payload:activeDeviceId',
  serial: 'payload:serialDeviceId',
  udp: 'payload:udpDeviceId'
}
/** 首页选中的活动设备偏好有效期 8h */
export const ACTIVE_DEVICE_TTL_MS = 8 * 60 * 60 * 1000

const DEFAULT_PARTS = [
  'can',
  'serialList',
  'serialOpened',
  'netOpened',
  'sessions',
  'parsers',
  'assemblers'
]

let memory = null // { data, at, parts }

function now() {
  return Date.now()
}

function readSession() {
  try {
    const raw = sessionStorage.getItem(SNAPSHOT_KEY)
    if (!raw) return null
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object') return null
    return obj
  } catch {
    return null
  }
}

function writeSession(payload) {
  try {
    sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(payload))
  } catch {
    /* ignore quota */
  }
}

function clearSession() {
  try {
    sessionStorage.removeItem(SNAPSHOT_KEY)
  } catch {
    /* ignore */
  }
}

function mergeData(prev, next) {
  return { ...(prev || {}), ...(next || {}) }
}

/** 写入/合并快照到内存 + sessionStorage */
export function saveDeviceSnapshot(data, { ttlMs = SNAPSHOT_TTL_MS, parts = null } = {}) {
  const prev = memory?.data || readSession()?.data || {}
  const merged = mergeData(prev, data)
  const at = now()
  memory = { data: merged, at, parts: parts || memory?.parts || null }
  writeSession({
    data: merged,
    at,
    expiresAt: at + ttlMs,
    parts: parts || null
  })
  return merged
}

export function invalidateDeviceSnapshot() {
  memory = null
  clearSession()
}

/**
 * 读取未过期快照。
 * @param {{ maxAgeMs?: number, consume?: boolean }} opts
 */
export function takeDeviceSnapshot({ maxAgeMs = SNAPSHOT_TTL_MS, consume = false } = {}) {
  const mem = memory
  if (mem && now() - mem.at <= maxAgeMs) {
    const data = mem.data
    if (consume) {
      memory = null
      clearSession()
    }
    return data
  }
  const sess = readSession()
  if (!sess?.data) return null
  const expiresAt = Number(sess.expiresAt) || (Number(sess.at) || 0) + maxAgeMs
  if (now() > expiresAt) {
    clearSession()
    memory = null
    return null
  }
  // 同步回内存
  memory = { data: sess.data, at: Number(sess.at) || now(), parts: sess.parts || null }
  if (consume) {
    memory = null
    clearSession()
  }
  return sess.data
}

/** 预热连接状态（含 CAN / 串口 / UDP） */
export async function prefetchDeviceSnapshot(parts = DEFAULT_PARTS) {
  try {
    const list = Array.isArray(parts) && parts.length ? parts : DEFAULT_PARTS
    const res = await getDeviceSnapshot(list)
    const data = res.data || {}
    saveDeviceSnapshot(data, { parts: list })
    return data
  } catch {
    return null
  }
}

/** @deprecated 兼容旧名：等同 prefetchDeviceSnapshot（串口相关 parts） */
export async function prefetchSerialConnectMeta() {
  return prefetchDeviceSnapshot(['serialList', 'serialOpened', 'parsers', 'assemblers', 'can', 'netOpened', 'sessions'])
}

/** @deprecated 兼容旧名 */
export function takeSerialConnectMeta(opts = {}) {
  return takeDeviceSnapshot(opts)
}

function readActiveRaw(kind) {
  const key = ACTIVE_KEYS[kind]
  if (!key) return null
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeActiveRaw(kind, value) {
  const key = ACTIVE_KEYS[kind]
  if (!key) return
  try {
    if (value == null || value === '') localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

/** 保存活动设备（带有效期）；value 为空则清除 */
export function setActiveDevice(kind, deviceId, { ttlMs = ACTIVE_DEVICE_TTL_MS } = {}) {
  if (!deviceId) {
    writeActiveRaw(kind, null)
    return
  }
  writeActiveRaw(
    kind,
    JSON.stringify({
      id: String(deviceId),
      expiresAt: now() + ttlMs
    })
  )
}

/** 读取未过期的活动设备 id；过期或无效返回 '' */
export function getActiveDevice(kind) {
  const raw = readActiveRaw(kind)
  if (!raw) return ''
  // 兼容旧版纯字符串
  if (!raw.startsWith('{')) return raw
  try {
    const obj = JSON.parse(raw)
    const id = String(obj?.id || '').trim()
    const expiresAt = Number(obj?.expiresAt) || 0
    if (!id) return ''
    if (expiresAt && now() > expiresAt) {
      writeActiveRaw(kind, null)
      return ''
    }
    return id
  } catch {
    return raw
  }
}

export function clearActiveDevice(kind) {
  writeActiveRaw(kind, null)
}
