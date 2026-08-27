/** 设备 IO 日志轮询：getDeviceIoLog + lastSeq + 定时器 + in-flight。 */

import { getDeviceIoLog } from '@/api/payload/device'

/**
 * @param {{
 *   getDeviceId: () => string,
 *   getPollMs?: () => number,
 *   lastSeq: { value: number },
 *   onItems: (list: object[]) => void
 * }} opts
 */
export function useIoLogPoll(opts) {
  let pollTimer = null
  let pulling = false

  async function pullOnce() {
    const deviceId = opts.getDeviceId()
    if (!deviceId || pulling) return
    pulling = true
    try {
      const res = await getDeviceIoLog(deviceId, opts.lastSeq.value)
      const list = res.data?.items || []
      if (!list.length) return
      opts.onItems(list)
    } catch {
      /* ignore */
    } finally {
      pulling = false
    }
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPoll() {
    stopPoll()
    if (!opts.getDeviceId()) return
    const raw = opts.getPollMs ? Number(opts.getPollMs()) : 1500
    const ms = Math.max(800, raw || 1500)
    pollTimer = setInterval(pullOnce, ms)
  }

  return { pullOnce, startPoll, stopPoll }
}
