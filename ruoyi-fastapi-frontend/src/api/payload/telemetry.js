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

export function subscribeTelemetryCurve(data) {
  return request({ url: '/payload/telemetry/curve/subscribe', method: 'post', data })
}

export function getTelemetryCurveData(params) {
  return request({ url: '/payload/telemetry/curve/data', method: 'get', params })
}

/** 开发测试：注入已组帧的 CAN 遥测复合帧 */
export function injectCanYcTest(data) {
  return request({ url: '/payload/telemetry/dev/can-yc', method: 'post', data })
}
