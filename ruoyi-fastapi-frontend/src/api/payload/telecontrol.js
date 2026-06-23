import request from '@/utils/request'

export function getTelecontrolOrder(orderId, reload = false) {
  return request({ url: `/payload/telecontrol/order/${orderId}`, method: 'get', params: { reload } })
}

export function assembleTelecontrol(data) {
  return request({ url: '/payload/telecontrol/assemble', method: 'post', data })
}

export function sendTelecontrol(data) {
  return request({ url: '/payload/telecontrol/send', method: 'post', data })
}

export function getTelecontrolHistory(deviceId, limit = 50) {
  return request({ url: '/payload/telecontrol/history', method: 'get', params: { deviceId, limit } })
}

export function telecontrolControlOp(data) {
  return request({ url: '/payload/telecontrol/control/op', method: 'post', data })
}
