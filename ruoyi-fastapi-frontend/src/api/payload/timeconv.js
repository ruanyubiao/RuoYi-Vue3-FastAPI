import request from '@/utils/request'

/** 协议时间纪元列表（gpcan defs.EPOCH_UTC，含 none） */
export function listTimeconvEpochs() {
  return request({
    url: '/payload/device/timeconv/epochs',
    method: 'get'
  })
}
