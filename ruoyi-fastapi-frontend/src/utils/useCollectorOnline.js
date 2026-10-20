import { onMounted, onUnmounted, ref } from 'vue'
import { getDeviceSnapshot } from '@/api/payload/device'
import { getCollectorHost, setCollectorHost } from '@/utils/collectorHost'

/** 业务页每 3 秒看一次当前采集机是否在线。 */
export function useCollectorOnline() {
  const host = ref(getCollectorHost())
  const online = ref(true)
  let timer = null

  async function tick() {
    const selected = getCollectorHost()
    try {
      const res = await getDeviceSnapshot([], selected ? [selected] : null)
      const data = res.data || {}
      host.value = selected || data.collectorHost || ''
      if (!selected && data.collectorHost) setCollectorHost(data.collectorHost)
      online.value = data.collectorOnline !== false
    } catch {
      online.value = false
    }
  }

  onMounted(() => {
    tick()
    timer = setInterval(tick, 3000)
  })
  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { host, online }
}
