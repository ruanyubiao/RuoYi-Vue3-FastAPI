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

export function listDeviceSessions() {
  return request({ url: '/payload/device/sessions', method: 'get' })
}

/** 绑定/解绑解释器；parserId 为空表示解绑 */
export function bindDeviceParser(data) {
  return request({ url: '/payload/device/bind-parser', method: 'post', data })
}
