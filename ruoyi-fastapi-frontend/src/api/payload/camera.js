import request from '@/utils/request'

export function startCamera(data) {
  return request({ url: '/payload/camera/start', method: 'post', data })
}

export function stopCamera(port) {
  return request({ url: '/payload/camera/stop', method: 'post', params: { port } })
}

export function getCameraImage(port) {
  return request({ url: '/payload/camera/image', method: 'get', params: { port } })
}

export function getCameraStatus(port) {
  return request({ url: '/payload/camera/status', method: 'get', params: { port } })
}

export function getCameraTelecontrolConfig(reload = false) {
  return request({ url: '/payload/camera/telecontrol/config', method: 'get', params: { reload } })
}

export function getCameraTelemetryConfig(reload = false) {
  return request({ url: '/payload/camera/telemetry/config', method: 'get', params: { reload } })
}

export function assembleCameraTelecontrol(data) {
  return request({
    url: '/payload/camera/telecontrol/assemble',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function sendCameraTelecontrol(data) {
  return request({
    url: '/payload/camera/telecontrol/send',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}
