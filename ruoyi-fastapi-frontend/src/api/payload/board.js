import request from '@/utils/request'

/**
 * 单板接口：/payload/board/{family}/{board}/...
 * @param {string} family 总线族，如 xl
 * @param {string} board 单板名，如 rkdj | zk | dj | cpazx
 */
export function getBoardTelecontrolConfig(family, board, reload = false) {
  return request({
    url: `/payload/board/${family}/${board}/telecontrol/config`,
    method: 'get',
    params: { reload }
  })
}

export function getBoardTelemetryConfig(family, board, reload = false) {
  return request({
    url: `/payload/board/${family}/${board}/telemetry/config`,
    method: 'get',
    params: { reload }
  })
}

export function assembleBoardTelecontrol(family, board, data) {
  return request({
    url: `/payload/board/${family}/${board}/telecontrol/assemble`,
    method: 'post',
    data,
    headers: { repeatSubmit: false }
  })
}

export function sendBoardTelecontrol(family, board, data) {
  const t = data && data.t
  const body = data && t != null ? { ...data } : data
  if (body && t != null) delete body.t
  return request({
    url: `/payload/board/${family}/${board}/telecontrol/send`,
    method: 'post',
    data: body,
    params: t != null ? { t } : undefined,
    headers: { repeatSubmit: false }
  })
}
