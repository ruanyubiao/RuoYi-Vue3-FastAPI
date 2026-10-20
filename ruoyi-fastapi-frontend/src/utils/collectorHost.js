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
