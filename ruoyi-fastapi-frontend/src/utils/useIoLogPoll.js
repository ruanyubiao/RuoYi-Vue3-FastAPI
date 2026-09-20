/** 设备 IO 日志轮询：getDeviceIoLog + lastSeq + 定时器 + in-flight。 */

import { getDeviceIoLog } from '@/api/payload/device'
import { takeIoLogItems } from '@/utils/ioLogSeq'

const DEFAULT_POLL_MS = 1000
const JITTER_MIN_MS = 50
const JITTER_MAX_MS = 500

/**
 * @param {{
 *   getDeviceId: () => string,
 *   getPollMs?: () => number,
 *   getKind?: () => string,
 *   getIncludeDevices?: () => boolean,
 *   lastSeq: { value: number },
 *   onItems: (list: object[]) => void,
 *   onMeta?: (data: object) => void
 * }} opts
 */
export function useIoLogPoll(opts) {
  let pollTimer = null
  let startDelayTimer = null
  let pulling = false
  let pullGen = 0

  function invalidate() {
    pullGen += 1
    pulling = false
  }

  async function pullOnce() {
    const deviceId = opts.getDeviceId()
    if (!deviceId || pulling) return
    pulling = true
    const gen = pullGen
    try {
      const kind = opts.getKind ? opts.getKind() : 'preview'
      const extras = opts.getIncludeDevices?.() ? { includeDevices: true } : {}
      const res = await getDeviceIoLog(deviceId, opts.lastSeq.value, 1000, kind, extras)
      if (gen !== pullGen) return
      const data = res.data || {}
      if (opts.onMeta) opts.onMeta(data)
      const list = data.items || []
      if (!list.length) return
      const { items, nextSeq } = takeIoLogItems(list, opts.lastSeq.value)
      if (!items.length) return
      opts.onItems(items)
      if (gen !== pullGen) return
      opts.lastSeq.value = nextSeq
    } catch {
      /* ignore */
    } finally {
      pulling = false
    }
  }

  function stopPoll() {
    invalidate()
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

  return { pullOnce, startPoll, stopPoll, invalidate }
}
