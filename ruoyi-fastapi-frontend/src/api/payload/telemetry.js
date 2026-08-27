import request from '@/utils/request'

export function getTelemetryTable(type, dataId = '', needCfg = false, source = 'live') {
  return request({
    url: '/payload/telemetry/table',
    method: 'get',
    params: {
      type,
      dataId: dataId || undefined,
      needCfg: needCfg ? 1 : undefined,
      source: source || 'live'
    }
  })
}

/** 批量获取遥测表：items 字段与 GET 一致（type/dataId/needCfg/source） */
export function getTelemetryTableBatch(items) {
  return request({
    url: '/payload/telemetry/table/batch',
    method: 'post',
    data: { items: items || [] },
    headers: { repeatSubmit: false }
  })
}

export function getTelemetryFields(type, family, reload = false) {
  return request({
    url: '/payload/telemetry/fields',
    method: 'get',
    params: { type, reload, ...(family ? { family } : {}) }
  })
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

export function uploadTelemetryFileChunk(formData, { signal, onUploadProgress, params } = {}) {
  return request({
    url: '/payload/telemetry/file/upload',
    method: 'post',
    data: formData,
    params: params || {},
    headers: { repeatSubmit: false },
    timeout: 0,
    signal,
    onUploadProgress
  })
}

export function browseTelemetryFiles(params) {
  return request({ url: '/payload/telemetry/file/browse', method: 'get', params })
}

export function locateTelemetryFile(params) {
  return request({ url: '/payload/telemetry/file/locate', method: 'get', params })
}

/** 通知后端开始解析，立即返回；结果用 getTelemetryFileStatus 轮询 */
export function parseTelemetryFile(data) {
  return request({
    url: '/payload/telemetry/file/parse',
    method: 'post',
    data,
    timeout: 15000,
    headers: { repeatSubmit: false }
  })
}

export function getTelemetryFileStatus(params) {
  return request({
    url: '/payload/telemetry/file/status',
    method: 'get',
    params,
    timeout: 8000,
    headers: { repeatSubmit: false }
  })
}

/**
 * 点解析：先 kickoff，再按 interval 拉 status，ready/error 后停表。
 * timeoutMs 由前端控制。返回 { promise, stop }，换文件/卸载时 stop。
 */
export function startFileParsePoll({
  type,
  path,
  timeoutMs = 60000,
  intervalMs = 400
} = {}) {
  let stopped = false
  let waitTimer = null
  const sleep = ms =>
    new Promise(resolve => {
      waitTimer = setTimeout(resolve, ms)
    })
  const stop = () => {
    stopped = true
    if (waitTimer) {
      clearTimeout(waitTimer)
      waitTimer = null
    }
  }
  const promise = (async () => {
    await parseTelemetryFile({ type, path })
    const t0 = Date.now()
    while (!stopped) {
      try {
        const res = await getTelemetryFileStatus({ path })
        const data = res.data || {}
        if (data.status === 'ready') return data
        if (data.status === 'error') {
          const err = new Error(data.error || '解析失败')
          err.parseFailed = true
          throw err
        }
      } catch (e) {
        if (e?.parseFailed) throw e
        if (Date.now() - t0 >= timeoutMs) {
          throw new Error('解析超时：文件解析进程未返回结果，请查看 logs/fileplay_worker.log')
        }
      }
      if (Date.now() - t0 >= timeoutMs) {
        throw new Error('解析超时：文件解析进程未返回结果，请查看 logs/fileplay_worker.log')
      }
      await sleep(intervalMs)
    }
    throw new Error('已取消解析')
  })()
  return { promise, stop }
}

export function getTelemetryFileFrame(params) {
  return request({
    url: '/payload/telemetry/file/frame',
    method: 'get',
    params,
    timeout: 8000,
    headers: { repeatSubmit: false }
  })
}

export function getTelemetryFileCurve(data) {
  return request({
    url: '/payload/telemetry/file/curve',
    method: 'post',
    data,
    timeout: 120000,
    headers: { repeatSubmit: false }
  })
}

export function openTelemetryHistoryFrames(data) {
  return request({
    url: '/payload/telemetry/history/frames/open',
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function getTelemetryHistoryFrame(params) {
  return request({
    url: '/payload/telemetry/history/frames',
    method: 'get',
    params,
    timeout: 8000,
    headers: { repeatSubmit: false }
  })
}

/** 开发测试：注入已组帧的 CAN 遥测复合帧 */
export function injectCanYcTest(data) {
  return request({ url: '/payload/telemetry/dev/can-yc', method: 'post', data })
}

/** 通用数据发送模拟：按组装器+解析器取黄金样本 HEX */
export function getSimulateSample(params) {
  return request({
    url: '/payload/telemetry/dev/sample',
    method: 'get',
    params,
    headers: { repeatSubmit: false }
  })
}

/** 通用数据发送模拟：HEX → 组装器 → 解析器 */
export function injectPipelineTest(data) {
  return request({ url: '/payload/telemetry/dev/pipeline', method: 'post', data })
}
