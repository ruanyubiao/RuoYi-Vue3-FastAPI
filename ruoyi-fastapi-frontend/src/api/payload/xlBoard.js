import request from '@/utils/request'

/** @param {'rkdj'|'zk'|'dj'|'cpazx'} board */
export function getXlBoardTelecontrolConfig(board, reload = false) {
  return request({
    url: `/payload/board/${board}/telecontrol/config`,
    method: 'get',
    params: { reload }
  })
}

/** @param {'rkdj'|'zk'|'dj'|'cpazx'} board */
export function getXlBoardTelemetryConfig(board, reload = false) {
  return request({
    url: `/payload/board/${board}/telemetry/config`,
    method: 'get',
    params: { reload }
  })
}

/** @param {'rkdj'|'zk'|'dj'|'cpazx'} board */
export function assembleXlBoardTelecontrol(board, data) {
  return request({
    url: `/payload/board/${board}/telecontrol/assemble`,
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

/** @param {'rkdj'|'zk'|'dj'|'cpazx'} board */
export function sendXlBoardTelecontrol(board, data) {
  const t = data && data.t
  const body = data && t != null ? { ...data } : data
  if (body && t != null) delete body.t
  return request({
    url: `/payload/board/${board}/telecontrol/send`,
    method: 'post',
    data: body,
    params: t != null ? { t } : undefined,
    headers: { repeatSubmit: false }
  })
}
