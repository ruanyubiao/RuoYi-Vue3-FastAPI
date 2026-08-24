/**
 * 设备默认连接配置（后端 assets/config/cfg_device_connect.json）。
 * key = 新建连接来源唯一标识（camera_ctrl / biu_can_a / xl_can_b / rkdj …）。
 * 首页（home）不在此配置，新建连接不限制。
 */
import { getDeviceConnectDefaults } from '@/api/payload/device'

let _cache = null
let _loading = null

export async function loadDeviceConnectMap(force = false) {
  if (!force && _cache) return _cache
  if (!force && _loading) return _loading
  _loading = getDeviceConnectDefaults()
    .then(res => {
      const data = res.data
      _cache = data && typeof data === 'object' ? data : {}
      return _cache
    })
    .catch(() => {
      _cache = _cache || {}
      return _cache
    })
    .finally(() => {
      _loading = null
    })
  return _loading
}

export function peekDeviceConnectMap() {
  return _cache || {}
}

/** 取配置项（key=来源唯一标识，如 camera_ctrl / biu_can_a） */
export async function getDeviceConnectEntry(key) {
  const map = await loadDeviceConnectMap()
  const entry = map?.[key]
  return entry && typeof entry === 'object' ? entry : null
}

export function toSerialPreset(entry) {
  const baud = Number(entry?.baudrate ?? entry?.baudChoice) || 115200
  return {
    baudChoice: baud,
    baudrate: baud,
    dataBits: Number(entry?.dataBits) || 8,
    stopBits: Number(entry?.stopBits) || 1,
    parity: entry?.parity || 'N',
    flowControl: entry?.flowControl || 'NONE',
    assemblerId: entry?.assemblerId || 'passthrough',
    parserId: entry?.parserId || '',
    fullDuplex: entry?.fullDuplex === true
  }
}

export function toBaudChoices(entry) {
  const raw = Array.isArray(entry?.baudChoices) && entry.baudChoices.length
    ? entry.baudChoices
    : [Number(entry?.baudrate ?? entry?.baudRate) || 115200]
  return raw.map(v => {
    const n = Number(v)
    return { value: n, label: String(n) }
  })
}

/**
 * CAN 默认连接预设（遥控 BIU/XL 用；不含 cableFlag/canIndex/devIndex）。
 * @param {object|null} entry cfg 条目
 * @param {{ assemblerId?: string, parserId?: string, nodeAddrTo?: number }} [fallback]
 */
export function toCanPreset(entry, fallback = {}) {
  const baud = Number(entry?.baudRate) || 500
  const choices =
    Array.isArray(entry?.baudChoices) && entry.baudChoices.length
      ? entry.baudChoices.map(v => Number(v)).filter(n => Number.isFinite(n))
      : [baud]
  return {
    baudRate: baud,
    baudChoices: choices.length ? choices : [500],
    assemblerId: entry?.assemblerId || fallback.assemblerId || 'can_biu',
    parserId: entry?.parserId || fallback.parserId || 'tm_can_biu',
    nodeAddrTo: fallback.nodeAddrTo != null ? Number(fallback.nodeAddrTo) : undefined,
    fullDuplex: entry?.fullDuplex === true
  }
}
