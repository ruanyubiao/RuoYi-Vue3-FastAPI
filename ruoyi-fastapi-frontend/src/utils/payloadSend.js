import { ElMessage } from 'element-plus'

/** 按 deviceId / srcParam 推断通道中文名 */
export function channelLabelFromDeviceId(deviceId) {
  const id = String(deviceId || '').toLowerCase()
  if (id.startsWith('can:')) return 'CAN'
  if (id.startsWith('serial:') || id.startsWith('com')) return '串口'
  if (id.startsWith('udp:') || id.includes(':udp:')) return 'UDP'
  if (id.startsWith('net:')) return '网络'
  if (id.startsWith('http:')) return 'HTTP'
  return ''
}

/**
 * 统一发送结果提示（遥控指令 / CAN 原始 / 串口 / UDP 等）。
 * @param {object} apiRes request 拦截器返回体 `{ code, msg, data }`
 * @param {{ deviceId?: string, channel?: string }} [options]
 * @returns {boolean} 是否成功
 */
export function notifyPayloadSendResult(apiRes, options = {}) {
  const data = apiRes?.data ?? {}
  const ok = !!data.success
  const channel = options.channel || channelLabelFromDeviceId(options.deviceId)
  const prefix = channel ? `${channel} ` : ''
  if (ok) {
    ElMessage.success(`${prefix}发送成功`)
  } else {
    ElMessage.error(data.message || `${prefix}发送失败`)
  }
  return ok
}
