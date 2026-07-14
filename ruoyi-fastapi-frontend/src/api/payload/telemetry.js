import request from '@/utils/request'

export function getTelemetryTable(deviceId, type, dataId = '', needCfg = false) {
  return request({
    url: '/payload/telemetry/table',
    method: 'get',
    params: {
      deviceId,
      type,
      dataId: dataId || undefined,
      needCfg: needCfg ? 1 : undefined
    }
  })
}

export function getTelemetryFields(type, reload = false) {
  return request({ url: '/payload/telemetry/fields', method: 'get', params: { type, reload } })
}

export function getTelemetryCurveData(params) {
  return request({ url: '/payload/telemetry/curve/data', method: 'get', params })
}

export function getTelemetryCurveDataBatch(items) {
  return request({
    url: '/payload/telemetry/curve/data/batch',
    method: 'post',
    data: { items },
    headers: { repeatSubmit: false }
  })
}

/** 归档遥测：按时间区间从 MySQL 批量拉取曲线点 */
export function getTelemetryHistoryCurveDataBatch(items) {
  return request({
    url: '/payload/telemetry/history/curve/batch',
    method: 'post',
    data: { items },
    headers: { repeatSubmit: false }
  })
}

/** 开发测试：注入已组帧的 CAN 遥测复合帧 */
export function injectCanYcTest(data) {
  return request({ url: '/payload/telemetry/dev/can-yc', method: 'post', data })
}
