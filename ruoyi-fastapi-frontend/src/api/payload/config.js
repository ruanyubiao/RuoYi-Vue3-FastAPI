import request from '@/utils/request'

// 获取遥控配置(分类页 + 指令定义)；family=biu|xl
export function getTelecontrolConfig(reload = false, family = 'biu') {
  return request({
    url: '/payload/telecontrol/config',
    method: 'get',
    params: { reload, family }
  })
}

// 获取遥测表列表(由配置 table 派生，用于遥测表切换下拉)；family 可选
export function getTelemetryConfig(reload = false, family) {
  return request({
    url: '/payload/telemetry/config',
    method: 'get',
    params: { reload, ...(family ? { family } : {}) }
  })
}

// 获取某遥测表的字段定义(用于表头/描述与曲线遥测量下拉)
export function getTelemetryDef(type, reload = false, family) {
  return request({
    url: '/payload/telemetry/def',
    method: 'get',
    params: { type, reload, ...(family ? { family } : {}) }
  })
}
