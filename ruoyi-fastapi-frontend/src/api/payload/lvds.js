import request from '@/utils/request'

export function listLvdsSignals(type = '7E9B') {
  return request({ url: '/payload/lvds/signals', method: 'get', params: { type } })
}

export function getLvdsData(params) {
  return request({ url: '/payload/lvds/data', method: 'get', params })
}
