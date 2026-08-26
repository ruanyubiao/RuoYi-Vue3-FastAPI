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

/**
 * 连接来源唯一 key → 列表「来源」短名。
 * home 不在 cfg_device_connect；其余 key 与 cfg 条目一致。
 * 未写入本表时回退已加载 cfg 的 label，避免再漏一项。
 */
export const CONNECT_SOURCE_LABEL = {
  home: '首页',
  camera_ctrl: '相机·控制',
  camera_image: '相机·图像',
  rkdj: '热控电机',
  zk: 'CPA-ZK',
  biu_can_a: 'BIU CAN-A',
  biu_can_b: 'BIU CAN-B',
  xl_can_a: 'XL CAN-A',
  xl_can_b: 'XL CAN-B',
  xl_udp_dj: '地检板'
}

export function connectSourceLabel(source, empty = '') {
  const id = String(source || '').trim()
  if (!id) return empty
  if (CONNECT_SOURCE_LABEL[id]) return CONNECT_SOURCE_LABEL[id]
  const cfgLabel = peekDeviceConnectMap()?.[id]?.label
  if (cfgLabel) return String(cfgLabel)
  return id
}

/**
 * cfg_device_connect 某字段非空则锁定对应输入框；空字符串不限制。
 * 首页不绑 key、不传 preset，因此不会锁。
 */
export function isConnectCfgFieldLocked(value) {
  return value != null && String(value).trim() !== ''
}

/**
 * UDP 远程对端校验。端口 0 表示未指定端口。
 * 可只填地址不填端口；填了非 0 端口则必须同时有地址，且端口为 1–65535。
 */
export function udpRemotePeerError(remoteHost, remotePort) {
  const host = String(remoteHost || '').trim()
  const port = Number(remotePort)
  if (!Number.isFinite(port) || port < 0 || port > 65535 || port !== Math.trunc(port)) {
    return '远程端口无效（0 表示未指定，其它须为 1–65535）'
  }
  if (!host && port !== 0) {
    return '未填写远程地址时端口须为 0（表示未指定端口）'
  }
  return ''
}

/** 取配置项（key=来源唯一标识，如 camera_ctrl / biu_can_a） */
export async function getDeviceConnectEntry(key) {
  const map = await loadDeviceConnectMap()
  const entry = map?.[key]
  return entry && typeof entry === 'object' ? entry : null
}

export function toSerialPreset(entry) {
  const baud = Number(entry?.baudrate ?? entry?.baudChoice) || 115200
  const assemblerId = isConnectCfgFieldLocked(entry?.assemblerId)
    ? String(entry.assemblerId).trim()
    : 'passthrough'
  const parserId = isConnectCfgFieldLocked(entry?.parserId) ? String(entry.parserId).trim() : ''
  return {
    baudChoice: baud,
    baudrate: baud,
    dataBits: Number(entry?.dataBits) || 8,
    stopBits: Number(entry?.stopBits) || 1,
    parity: entry?.parity || 'N',
    flowControl: entry?.flowControl || 'NONE',
    assemblerId,
    parserId,
    // 锁以 cfg 原文为准，避免空字段被默认值填满后误锁
    lockAssembler: isConnectCfgFieldLocked(entry?.assemblerId),
    lockParser: isConnectCfgFieldLocked(entry?.parserId),
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
 * UDP 默认连接预设。
 * 远程不进 deviceId，只作为采集默认发送对端。
 * 页面若传入该预设（绑定 cfg_device_connect 的 key，如 xl_udp_dj），对话框锁死本机/远程；
 * 首页不传预设，输入框可改。
 * @param {object|null} entry cfg 条目
 */
export function toUdpPreset(entry) {
  const localPort = Number(entry?.localPort)
  const remotePort = Number(entry?.remotePort)
  return {
    localHost: entry?.localHost ? String(entry.localHost) : '0.0.0.0',
    localPort: Number.isFinite(localPort) && localPort > 0 ? localPort : 9000,
    remoteHost: entry?.remoteHost != null ? String(entry.remoteHost) : '',
    remotePort: Number.isFinite(remotePort) && remotePort >= 0 ? remotePort : 0,
    assemblerId: isConnectCfgFieldLocked(entry?.assemblerId)
      ? String(entry.assemblerId).trim()
      : 'passthrough',
    parserId: isConnectCfgFieldLocked(entry?.parserId) ? String(entry.parserId).trim() : '',
    lockAssembler: isConnectCfgFieldLocked(entry?.assemblerId),
    lockParser: isConnectCfgFieldLocked(entry?.parserId),
    fullDuplex: entry?.fullDuplex === true
  }
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
    assemblerId: isConnectCfgFieldLocked(entry?.assemblerId)
      ? String(entry.assemblerId).trim()
      : fallback.assemblerId || 'can_biu',
    parserId: isConnectCfgFieldLocked(entry?.parserId)
      ? String(entry.parserId).trim()
      : fallback.parserId || 'tm_can_biu',
    lockAssembler: isConnectCfgFieldLocked(entry?.assemblerId),
    lockParser: isConnectCfgFieldLocked(entry?.parserId),
    nodeAddrTo: fallback.nodeAddrTo != null ? Number(fallback.nodeAddrTo) : undefined,
    fullDuplex: entry?.fullDuplex === true
  }
}
