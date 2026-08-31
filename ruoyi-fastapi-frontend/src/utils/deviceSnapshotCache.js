import { getDeviceSnapshot } from '@/api/payload/device'
import cache from '@/plugins/cache'

/** 连接状态快照（串口/CAN/UDP），切换页面可复用 */
const SNAPSHOT_KEY = 'payload:deviceSnapshot:v1'
export const SNAPSHOT_TTL_MS = 30_000

const ACTIVE_KEYS = {
  can: 'payload:activeDeviceId',
  serial: 'payload:serialDeviceId',
  udp: 'payload:udpDeviceId'
}
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
  const obj = cache.session.getJSON(SNAPSHOT_KEY)
  return obj && typeof obj === 'object' ? obj : null
}

function writeSession(payload) {
  cache.session.setJSON(SNAPSHOT_KEY, payload)
}

function clearSession() {
  cache.session.remove(SNAPSHOT_KEY)
}

function mergeData(prev, next) {
  return { ...(prev || {}), ...(next || {}) }
}

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
  memory = { data: sess.data, at: Number(sess.at) || now(), parts: sess.parts || null }
  if (consume) {
    memory = null
    clearSession()
  }
  return sess.data
}

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

/** @deprecated */
export async function prefetchSerialConnectMeta() {
  return prefetchDeviceSnapshot(['serialList', 'serialOpened', 'parsers', 'assemblers', 'can', 'netOpened', 'sessions'])
}

/** @deprecated */
export function takeSerialConnectMeta(opts = {}) {
  return takeDeviceSnapshot(opts)
}

function activeKey(kind) {
  return ACTIVE_KEYS[kind] || ''
}

export function setActiveDevice(kind, deviceId, { ttlMs = ACTIVE_DEVICE_TTL_MS } = {}) {
  const key = activeKey(kind)
  if (!key) return
  if (!deviceId) {
    cache.expire.remove(key)
    cache.local.remove(key)
    return
  }
  cache.expire.setJSON(key, { id: String(deviceId) }, Math.max(1, Math.ceil(ttlMs / 1000)))
}

export function getActiveDevice(kind) {
  const key = activeKey(kind)
  if (!key) return ''
  const fromExpire = cache.expire.getJSON(key)
  if (fromExpire && typeof fromExpire === 'object' && fromExpire.id) {
    return String(fromExpire.id).trim()
  }
  const raw = cache.local.get(key)
  if (!raw) return ''
  if (!String(raw).startsWith('{')) return raw
  try {
    const obj = JSON.parse(raw)
    if (obj && 'c' in obj && 'e' in obj && 'v' in obj) return ''
    const id = String(obj?.id || '').trim()
    const expiresAt = Number(obj?.expiresAt) || 0
    if (!id) return ''
    if (expiresAt && now() > expiresAt) {
      cache.local.remove(key)
      return ''
    }
    return id
  } catch {
    return raw
  }
}

export function clearActiveDevice(kind) {
  setActiveDevice(kind, '')
}
