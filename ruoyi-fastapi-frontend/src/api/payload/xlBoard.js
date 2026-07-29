import request from '@/utils/request'

/** @param {'rkdj'|'zk'} board */
export function getXlBoardTelecontrolConfig(board, reload = false) {
  return request({
    url: `/payload/board/${board}/telecontrol/config`,
    method: 'get',
    params: { reload }
  })
}

/** @param {'rkdj'|'zk'} board */
export function getXlBoardTelemetryConfig(board, reload = false) {
  return request({
    url: `/payload/board/${board}/telemetry/config`,
    method: 'get',
    params: { reload }
  })
}

/** @param {'rkdj'|'zk'} board */
export function getXlBoardTelemetryTable(board, dataId = null, needCfg = false) {
  return request({
    url: `/payload/board/${board}/telemetry/table`,
    method: 'get',
    params: { dataId, needCfg }
  })
}

/** @param {'rkdj'|'zk'} board */
export function assembleXlBoardTelecontrol(board, data) {
  return request({
    url: `/payload/board/${board}/telecontrol/assemble`,
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

/** @param {'rkdj'|'zk'} board */
export function sendXlBoardTelecontrol(board, data) {
  return request({
    url: `/payload/board/${board}/telecontrol/send`,
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}
