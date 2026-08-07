import request from '@/utils/request'

export function listCanVendors() {
  return request({ url: '/payload/device/can/vendors', method: 'get' })
}

export function listCanChannels() {
  return request({ url: '/payload/device/can/list', method: 'get' })
}

export function openCanChannel(data) {
  return request({ url: '/payload/device/can/open', method: 'post', data })
}

export function closeCanChannel(data) {
  return request({ url: '/payload/device/can/close', method: 'post', data })
}

/** 热更新已打开 CAN 通道的目标地址 / 线缆 */
export function setCanCable(data) {
  return request({ url: '/payload/device/can/cable', method: 'post', data })
}

export function listSerialPorts() {
  return request({ url: '/payload/device/serial/list', method: 'get' })
}

export function listSerialOpened() {
  return request({ url: '/payload/device/serial/opened', method: 'get' })
}

export function openSerialPort(data) {
  return request({ url: '/payload/device/serial/open', method: 'post', data })
}

export function closeSerialPort(port) {
  return request({ url: '/payload/device/serial/close', method: 'post', params: { port } })
}

export function getDeviceStatus(deviceId) {
  return request({ url: '/payload/device/status', method: 'get', params: { deviceId } })
}

export function listParsers() {
  return request({ url: '/payload/device/parsers', method: 'get' })
}

export function listAssemblers(srcKind) {
  return request({
    url: '/payload/device/assemblers',
    method: 'get',
    params: srcKind ? { srcKind } : undefined
  })
}

/** 设备默认连接配置（cfg_device_connect.json）；key 为空返回全部 */
export function getDeviceConnectDefaults(key) {
  return request({
    url: '/payload/device/connect-defaults',
    method: 'get',
    params: key ? { key } : undefined
  })
}

export function listDeviceSessions() {
  return request({ url: '/payload/device/sessions', method: 'get' })
}

/**
 * 设备只读数据批量快照，减少并发请求。
 * @param {string[]|string} parts can|serialList|serialOpened|netOpened|sessions|parsers|assemblers
 */
export function getDeviceSnapshot(parts = []) {
  const value = Array.isArray(parts) ? parts.filter(Boolean).join(',') : String(parts || '')
  return request({
    url: '/payload/device/snapshot',
    method: 'get',
    params: { parts: value }
  })
}

/** 绑定/解绑解释器与组装器；parserId 为空表示解绑解释器 */
export function bindDeviceParser(data) {
  return request({ url: '/payload/device/bind-parser', method: 'post', data })
}

export function listLocalAddresses() {
  return request({ url: '/payload/device/net/addresses', method: 'get' })
}

export function listNetOpened() {
  return request({ url: '/payload/device/net/opened', method: 'get' })
}

export function openNet(data) {
  return request({ url: '/payload/device/net/open', method: 'post', data })
}

export function closeNet(data) {
  return request({ url: '/payload/device/net/close', method: 'post', data })
}

/** 一次性关闭全部 CAN / 串口 / UDP */
export function closeAllDevices() {
  return request({
    url: '/payload/device/close-all',
    method: 'post',
    headers: { repeatSubmit: false }
  })
}

export function getDeviceIoLog(deviceId, sinceSeq = 0, limit = 200) {
  return request({
    url: '/payload/device/io-log',
    method: 'get',
    params: { deviceId, sinceSeq, limit }
  })
}

export function clearDeviceIoLog(deviceId) {
  return request({
    url: '/payload/device/io-log',
    method: 'delete',
    params: { deviceId }
  })
}
