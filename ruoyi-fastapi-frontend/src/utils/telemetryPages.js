import { getTelemetryConfig } from '@/api/payload/config'

/** 遥测表页列表进程内缓存：各页下拉共用，切换选项不再打 /telemetry/config */
let pages = null
let pending = null

export async function loadTelemetryPagesCached() {
  if (pages) return pages
  if (!pending) {
    pending = getTelemetryConfig()
      .then(res => {
        pages = (res.data?.page || []).filter(p => p && p.key)
        return pages
      })
      .finally(() => {
        pending = null
      })
  }
  return pending
}
