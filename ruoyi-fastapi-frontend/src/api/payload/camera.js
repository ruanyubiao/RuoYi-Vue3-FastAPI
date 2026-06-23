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
