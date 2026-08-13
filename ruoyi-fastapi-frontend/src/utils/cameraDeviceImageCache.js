/**
 * 相机页设备采图浏览器缓存。仅缓存设备下发图像，本地上传不写入。
 * 有效期默认 10 分钟；有新采图则覆盖。
 */

const KEY = 'payload:camera:deviceImage:v1'
export const DEVICE_IMAGE_TTL_MS = 10 * 60 * 1000

function now() {
  return Date.now()
}

/**
 * @returns {{ src: string, width: number, height: number, imageNo: any, refreshTime: string, at: number } | null}
 */
export function takeDeviceImageCache({ maxAgeMs = DEVICE_IMAGE_TTL_MS } = {}) {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object' || !obj.src) {
      localStorage.removeItem(KEY)
      return null
    }
    const at = Number(obj.at) || 0
    if (!at || (maxAgeMs > 0 && now() - at > maxAgeMs)) {
      localStorage.removeItem(KEY)
      return null
    }
    return {
      src: String(obj.src),
      width: Number(obj.width) || 0,
      height: Number(obj.height) || 0,
      imageNo: obj.imageNo ?? null,
      refreshTime: obj.refreshTime || '',
      at
    }
  } catch {
    return null
  }
}

/**
 * @param {{ src: string, width?: number, height?: number, imageNo?: any, refreshTime?: string }} data
 */
export function saveDeviceImageCache(data) {
  if (!data?.src) return
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        at: now(),
        src: data.src,
        width: Number(data.width) || 0,
        height: Number(data.height) || 0,
        imageNo: data.imageNo ?? null,
        refreshTime: data.refreshTime || ''
      })
    )
  } catch {
    /* quota */
  }
}

export function clearDeviceImageCache() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}
