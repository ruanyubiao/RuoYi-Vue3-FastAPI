import { onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { getDeviceSnapshot, SNAPSHOT_POLL_MS } from '@/api/payload/device'
import { getCollectorHost, pickCollectorHost, setCollectorHost } from '@/utils/collectorHost'

/** 看当前采集机是否在线。点名的机器离线时保持这一台。poll 为 false 时只选机，不自建定时器。 */
export function useCollectorOnline(options = {}) {
  const poll = options.poll !== false
  const host = ref(getCollectorHost())
  const online = ref(true)
  let timer = null
  let skipActivate = false

  async function tick() {
    const selected = getCollectorHost()
    host.value = selected
    try {
      const res = await getDeviceSnapshot(selected ? [selected] : null)
      const data = res.data || {}
      const devices = Array.isArray(data.devices) ? data.devices : []
      if (selected) {
        const row = devices.find(item => item.host === selected)
        online.value = !!(row && row.online !== false)
        return
      }
      const picked = pickCollectorHost('', '', devices)
      host.value = picked
      if (devices.some(item => item.host === picked)) setCollectorHost(picked)
      online.value = devices.some(item => item.host === picked && item.online !== false)
    } catch {
      online.value = false
    }
  }

  function stop() {
    if (timer) clearInterval(timer)
    timer = null
  }

  function start() {
    stop()
    tick()
    if (!poll) return
    timer = setInterval(tick, SNAPSHOT_POLL_MS)
  }

  onMounted(() => {
    skipActivate = true
    start()
  })
  onActivated(() => {
    if (skipActivate) {
      skipActivate = false
      return
    }
    start()
  })
  onDeactivated(stop)
  onUnmounted(stop)

  return { host, online }
}
