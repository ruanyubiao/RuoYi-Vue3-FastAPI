/** keep-alive 页面链路检测：切走停定时器，回来再开。 */

import { onActivated, onDeactivated, onUnmounted } from 'vue'
import { SNAPSHOT_POLL_MS } from '@/api/payload/device'

/**
 * @param {() => void} tick
 * @param {number} [intervalMs] 默认与采集机状态轮询相同
 */
export function useLinkStatusPoll(tick, intervalMs = SNAPSHOT_POLL_MS) {
  let timer = null

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function start() {
    stop()
    const ms = Math.max(500, Number(intervalMs) || SNAPSHOT_POLL_MS)
    timer = setInterval(tick, ms)
  }

  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)

  return { start, stop }
}
