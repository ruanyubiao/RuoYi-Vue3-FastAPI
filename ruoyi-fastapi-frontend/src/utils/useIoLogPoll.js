/** 设备 IO 日志轮询：getDeviceIoLog + lastSeq + 定时器 + in-flight。 */

import { getDeviceIoLog } from '@/api/payload/device'

const DEFAULT_POLL_MS = 1000
const JITTER_MIN_MS = 50
const JITTER_MAX_MS = 500

/**
 * @param {{
 *   getDeviceId: () => string,
 *   getPollMs?: () => number,
 *   getKind?: () => string,
 *   lastSeq: { value: number },
 *   onItems: (list: object[]) => void
 * }} opts
 */
export function useIoLogPoll(opts) {
  let pollTimer = null
  let startDelayTimer = null
  let pulling = false

  async function pullOnce() {
    const deviceId = opts.getDeviceId()
    if (!deviceId || pulling) return
    pulling = true
    try {
      const kind = opts.getKind ? opts.getKind() : 'preview'
      const res = await getDeviceIoLog(deviceId, opts.lastSeq.value, 200, kind)
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
    if (startDelayTimer) {
      clearTimeout(startDelayTimer)
      startDelayTimer = null
    }
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function startPoll() {
    stopPoll()
    if (!opts.getDeviceId()) return
    const raw = opts.getPollMs ? Number(opts.getPollMs()) : DEFAULT_POLL_MS
    const ms = Math.max(800, raw || DEFAULT_POLL_MS)
    // 相对遥测 1s 错开相位；切走必须清掉 pending timeout
    const delay = JITTER_MIN_MS + Math.random() * (JITTER_MAX_MS - JITTER_MIN_MS)
    startDelayTimer = setTimeout(() => {
      startDelayTimer = null
      pullOnce()
      pollTimer = setInterval(pullOnce, ms)
    }, delay)
  }

  return { pullOnce, startPoll, stopPoll }
}
