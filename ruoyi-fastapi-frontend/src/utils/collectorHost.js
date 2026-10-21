import cache from '@/plugins/cache'

export const COLLECTOR_HOST_KEY = 'payload:collectorHost'

export function getCollectorHost() {
  return String(cache.local.get(COLLECTOR_HOST_KEY) || '').trim()
}

export function setCollectorHost(host) {
  const value = String(host || '').trim()
  if (value) cache.local.set(COLLECTOR_HOST_KEY, value)
  else cache.local.remove(COLLECTOR_HOST_KEY)
  window.dispatchEvent(new CustomEvent('collector-host-change', { detail: value }))
}

/** 已保存或接口返回的标识不在采集机列表里时，用列表第一项。一台都没有时用 local。 */
export function pickCollectorHost(saved, reported, collectors) {
  if (!Array.isArray(collectors)) {
    return String(saved || reported || 'local').trim() || 'local'
  }
  const options = collectors
    .map(item => String(item?.host || '').trim())
    .filter(Boolean)
  if (!options.length) return 'local'
  const current = String(saved || '').trim()
  if (current && options.includes(current)) return current
  const fallback = String(reported || '').trim()
  if (fallback && options.includes(fallback)) return fallback
  return options[0]
}
