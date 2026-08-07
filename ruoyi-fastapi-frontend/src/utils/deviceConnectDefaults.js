/**
 * 设备默认连接配置（后端 assets/config/cfg_device_connect.json）。
 * key = 新建连接来源唯一标识（camera_ctrl / camera_image / rkdj / zk …）。
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

/** 取配置项（key=来源唯一标识，如 camera_ctrl / rkdj） */
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
    parserId: entry?.parserId || ''
  }
}

export function toBaudChoices(entry) {
  const raw = Array.isArray(entry?.baudChoices) && entry.baudChoices.length
    ? entry.baudChoices
    : [Number(entry?.baudrate) || 115200]
  return raw.map(v => {
    const n = Number(v)
    return { value: n, label: String(n) }
  })
}
