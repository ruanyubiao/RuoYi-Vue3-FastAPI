/** keep-alive 页面链路检测：切走停定时器，回来再开。 */

import { onActivated, onDeactivated, onUnmounted } from 'vue'

/**
 * @param {() => void} tick
 * @param {number} [intervalMs]
 */
export function useLinkStatusPoll(tick, intervalMs = 2000) {
  let timer = null

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function start() {
    stop()
    const ms = Math.max(500, Number(intervalMs) || 2000)
    timer = setInterval(tick, ms)
  }

  onActivated(start)
  onDeactivated(stop)
  onUnmounted(stop)

  return { start, stop }
}
