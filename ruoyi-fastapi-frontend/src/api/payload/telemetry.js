import { h } from 'vue'
import { ElButton, ElMessageBox } from 'element-plus'
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

export function getTelemetryCurveDataBatch(items, { fps } = {}) {
  const data = { items }
  if (fps) data.fps = 1
  return request({
    url: '/payload/telemetry/curve/data/batch',
    method: 'post',
    data,
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

/** 点解析前查当前会话：进程活着且同文件已完成才弹窗；进程已死当新解析。 */
export function decideFileParseAction(data, type) {
  const d = data || {}
  if (!d.workerAlive || d.sessionGone) return 'parse'
  const thisFile =
    Number(d.frameCount) > 0 ||
    !!d.hasData ||
    d.status === 'ready' ||
    !!d.complete ||
    !!d.frameCountExact
  const sameType = !d.type || String(d.type).toUpperCase() === String(type || '').toUpperCase()
  if (thisFile && sameType) {
    if (d.complete || d.frameCountExact) return 'confirm'
    return 'parsing'
  }
  return 'parse'
}

/** 已完成会话：重新解析 / 取消 / 使用现有。 */
export function askCompletedFileParse() {
  return new Promise(resolve => {
    let settled = false
    const finish = action => {
      if (settled) return
      settled = true
      resolve(action)
    }
    ElMessageBox({
      title: '提示',
      type: 'warning',
      closeOnClickModal: false,
      showConfirmButton: false,
      showCancelButton: false,
      message: h('div', [
        h('p', { style: 'margin: 0' }, '已经解析完成，是否重新解析？'),
        h(
          'div',
          { style: 'margin-top: 16px; display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap' },
          [
            h(ElButton, { type: 'primary', onClick: () => { finish('reparse'); ElMessageBox.close() } }, () => '重新解析'),
            h(ElButton, { onClick: () => { finish('cancel'); ElMessageBox.close() } }, () => '取消'),
            h(ElButton, { onClick: () => { finish('use'); ElMessageBox.close() } }, () => '使用现有')
          ]
        )
      ]),
      callback: () => finish('cancel')
    }).catch(() => finish('cancel'))
  })
}

/**
 * 点解析：kickoff 后轮询 status。
 * 一旦 hasData/ready 就兑现 promise，后台继续拉到 complete（帧总数固定）。
 * timeoutMs 只约束「等到第一批数据」；换文件/卸载时 stop。
 */
export function startFileParsePoll({
  type,
  path,
  channel = 'history',
  timeoutMs = 60000,
  intervalMs = 400,
  onProgress,
  force
} = {}) {
  let stopped = false
  let waitTimer = null
  let pathHash = ''
  const ch = channel === 'curve' ? 'curve' : 'history'
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
  const statusParams = () => ({
    channel: ch,
    ...(pathHash ? { pathHash } : { path })
  })
  let resolveFirst
  let rejectFirst
  const firstPromise = new Promise((resolve, reject) => {
    resolveFirst = resolve
    rejectFirst = reject
  })
  const loop = (async () => {
    let signaled = false
    try {
      const kick = await parseTelemetryFile({
        type,
        path,
        channel: ch,
        ...(force ? { force: 1 } : {})
      })
      const kickData = kick.data || {}
      if (kickData.pathHash) pathHash = kickData.pathHash
      onProgress?.(kickData)
      const t0 = Date.now()
      const fail = err => {
        if (!signaled) {
          signaled = true
          rejectFirst(err)
        }
      }
      if (kickData.status === 'error') {
        const err = new Error(kickData.error || '解析失败')
        err.parseFailed = true
        fail(err)
        return
      }
      if (kickData.sessionGone && !kickData.workerAlive) {
        const err = new Error('文件解析进程未运行，请重新解析')
        err.parseFailed = true
        fail(err)
        return
      }
      if (kickData.hasData || kickData.status === 'ready' || kickData.frame) {
        signaled = true
        resolveFirst(kickData)
        if (kickData.complete || kickData.frameCountExact) return
      }
      while (!stopped) {
        try {
          const res = await getTelemetryFileStatus(statusParams())
          const data = res.data || {}
          if (data.pathHash) pathHash = data.pathHash
          onProgress?.(data)
          if (data.status === 'error') {
            const err = new Error(data.error || '解析失败')
            err.parseFailed = true
            fail(err)
            return
          }
          if (data.sessionGone && !data.workerAlive) {
            const err = new Error('文件解析进程未运行，请重新解析')
            err.parseFailed = true
            fail(err)
            return
          }
          const hasData = !!(data.hasData || data.status === 'ready' || data.frame)
          if (hasData && !signaled) {
            signaled = true
            resolveFirst(data)
          }
          if (data.complete || data.frameCountExact) return
        } catch (e) {
          if (e?.parseFailed) {
            fail(e)
            return
          }
          if (!signaled && Date.now() - t0 >= timeoutMs) {
            fail(new Error('解析超时：文件解析进程未返回结果'))
            return
          }
        }
        if (!signaled && Date.now() - t0 >= timeoutMs) {
          fail(new Error('解析超时：文件解析进程未返回结果'))
          return
        }
        await sleep(intervalMs)
      }
      fail(new Error('已取消解析'))
    } catch (e) {
      if (!signaled) rejectFirst(e)
    }
  })()
  return { promise: firstPromise, stop, done: loop, getPathHash: () => pathHash }
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

/** 通用数据发送模拟：按组装器+解析器列出可选黄金样本按钮 */
export function listSimulateSamples(params) {
  return request({
    url: '/payload/telemetry/dev/samples',
    method: 'get',
    params,
    headers: { repeatSubmit: false }
  })
}

/** 通用数据发送模拟：HEX → 组装器 → 解析器 */
export function injectPipelineTest(data) {
  return request({ url: '/payload/telemetry/dev/pipeline', method: 'post', data })
}
