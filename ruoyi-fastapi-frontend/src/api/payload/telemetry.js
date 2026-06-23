import request from '@/utils/request'

export function getTelemetryTable(deviceId, type) {
  return request({ url: '/payload/telemetry/table', method: 'get', params: { deviceId, type } })
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
