import request from '@/utils/request'

/** 遥测单字段计算 */
export function calcTelemetryField(data) {
  return request({
    url: '/payload/telemetry/calc',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

/** 遥测计算历史 */
export function getTelemetryCalcHistory() {
  return request({
    url: '/payload/telemetry/calc/history',
    method: 'get'
  })
}

/** 清空遥测计算历史 */
export function clearTelemetryCalcHistory() {
  return request({
    url: '/payload/telemetry/calc/history',
    method: 'delete'
  })
}
