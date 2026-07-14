import request from '@/utils/request'

export function getTelecontrolOrder(orderId, reload = false) {
  return request({ url: `/payload/telecontrol/order/${orderId}`, method: 'get', params: { reload } })
}

export function assembleTelecontrol(data) {
  return request({
    url: '/payload/telecontrol/assemble',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function sendTelecontrol(data) {
  return request({
    url: '/payload/telecontrol/send',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function sendCanRaw(data) {
  return request({
    url: '/payload/telecontrol/raw/can/send',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function getTelecontrolHistory(deviceId, limit = 50) {
  return request({ url: '/payload/telecontrol/history', method: 'get', params: { deviceId, limit } })
}

export function clearTelecontrolHistory(deviceId) {
  return request({ url: '/payload/telecontrol/history', method: 'delete', params: { deviceId } })
}

export function telecontrolControlOp(data) {
  return request({
    url: '/payload/telecontrol/control/op',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}
