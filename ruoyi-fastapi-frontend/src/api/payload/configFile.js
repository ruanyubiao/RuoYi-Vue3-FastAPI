import request from '@/utils/request'

export function listPayloadConfigFiles() {
  return request({
    url: '/payload/config-files/list',
    method: 'get'
  })
}

export function getPayloadConfigFileContent(name) {
  return request({
    url: '/payload/config-files/content',
    method: 'get',
    params: { name }
  })
}

export function savePayloadConfigFileContent(name, content) {
  return request({
    url: '/payload/config-files/content',
    method: 'put',
    data: { name, content }
  })
}

export function reloadPayloadConfigFiles(name) {
  return request({
    url: '/payload/config-files/reload',
    method: 'post',
    params: name ? { name } : undefined
  })
}

/** 导出遥控配置全部指令（默认参数组帧） */
export function exportPayloadConfigOrders(name) {
  return request({
    url: '/payload/config-files/export-orders',
    method: 'get',
    params: { name }
  })
}
