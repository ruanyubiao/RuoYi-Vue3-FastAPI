import request from '@/utils/request'

// 获取遥控配置(分类页 + 指令定义)
export function getTelecontrolConfig(reload = false) {
  return request({
    url: '/payload/telecontrol/config',
    method: 'get',
    params: { reload }
  })
}

// 获取遥测表列表(由配置 table 派生，用于遥测表切换下拉)
export function getTelemetryConfig(reload = false) {
  return request({
    url: '/payload/telemetry/config',
    method: 'get',
    params: { reload }
  })
}

// 获取某遥测表的字段定义(用于表头/描述与曲线遥测量下拉)
export function getTelemetryDef(type, reload = false) {
  return request({
    url: '/payload/telemetry/def',
    method: 'get',
    params: { type, reload }
  })
}
