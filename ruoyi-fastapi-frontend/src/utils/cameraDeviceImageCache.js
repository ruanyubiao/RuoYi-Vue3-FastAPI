/**
 * 相机页设备采图缓存。仅缓存设备下发图像；TTL 10 分钟（cache.expire）。
 */

import cache, { normalizeRecord } from '@/plugins/cache'

const KEY = 'payload:camera:deviceImage:v1'
export const DEVICE_IMAGE_TTL_MS = 10 * 60 * 1000
const TTL_SEC = Math.ceil(DEVICE_IMAGE_TTL_MS / 1000)

const DEVICE_IMAGE_DEFAULTS = {
  src: '',
  width: 0,
  height: 0,
  imageNo: null,
  refreshTime: '',
  at: 0
}

const DEVICE_IMAGE_SPEC = {
  src: v => String(v || ''),
  width: v => Number(v) || 0,
  height: v => Number(v) || 0,
  imageNo: v => v ?? null,
  refreshTime: v => v || '',
  at: v => Number(v) || 0
}

export function takeDeviceImageCache() {
  const raw = cache.expire.getJSON(KEY)
  if (!raw?.src) {
    if (raw != null) cache.expire.remove(KEY)
    return null
  }
  return normalizeRecord(raw, DEVICE_IMAGE_SPEC, DEVICE_IMAGE_DEFAULTS)
}

export function saveDeviceImageCache(data) {
  if (!data?.src) return
  cache.expire.setJSON(
    KEY,
    {
      src: data.src,
      width: Number(data.width) || 0,
      height: Number(data.height) || 0,
      imageNo: data.imageNo ?? null,
      refreshTime: data.refreshTime || '',
      at: Date.now()
    },
    TTL_SEC
  )
}

export function clearDeviceImageCache() {
  cache.expire.remove(KEY)
}
