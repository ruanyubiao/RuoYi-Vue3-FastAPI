import request from '@/utils/request'

export function startCamera(data) {
  return request({
    url: '/payload/camera/start',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function stopCamera(port) {
  return request({ url: '/payload/camera/stop', method: 'post', params: { port } })
}

/** since=上次已取到的图片相对路径；路径未变则后端只回状态、不读盘 */
export function getCameraImage(port, since = '') {
  return request({ url: '/payload/camera/image', method: 'get', params: { port, since } })
}

export function getCameraStatus(port) {
  return request({ url: '/payload/camera/status', method: 'get', params: { port } })
}

export function getCameraTelecontrolConfig(reload = false, protocol = 'v16') {
  return request({
    url: '/payload/camera/telecontrol/config',
    method: 'get',
    params: { reload, protocol }
  })
}

export function getCameraTelemetryConfig(reload = false, protocol = 'v16') {
  return request({
    url: '/payload/camera/telemetry/config',
    method: 'get',
    params: { reload, protocol }
  })
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
