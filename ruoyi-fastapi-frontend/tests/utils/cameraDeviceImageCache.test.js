import { describe, expect, it, vi } from 'vitest'
import cache from '@/plugins/cache'
import {
  clearDeviceImageCache,
  DEVICE_IMAGE_TTL_MS,
  saveDeviceImageCache,
  takeDeviceImageCache
} from '@/utils/cameraDeviceImageCache'

describe('utils/cameraDeviceImageCache', () => {
  const sample = {
    src: 'data:image/png;base64,abc',
    width: 640,
    height: 480,
    imageNo: 1,
    refreshTime: '2026-01-01 00:00:00'
  }

  it('save / take 往返', () => {
    saveDeviceImageCache(sample)
    const got = takeDeviceImageCache()
    expect(got?.src).toBe(sample.src)
    expect(got?.width).toBe(640)
    expect(got?.height).toBe(480)
  })

  it('无 src 视为无效并删除', () => {
    cache.expire.setJSON(
      'payload:camera:deviceImage:v1',
      { at: Date.now(), src: '', width: 1, height: 1 },
      600
    )
    expect(takeDeviceImageCache()).toBeNull()
    expect(cache.expire.getJSON('payload:camera:deviceImage:v1')).toBeNull()
  })

  it('过期后返回 null', () => {
    vi.useFakeTimers()
    saveDeviceImageCache(sample)
    vi.advanceTimersByTime(DEVICE_IMAGE_TTL_MS + 1)
    expect(takeDeviceImageCache()).toBeNull()
    vi.useRealTimers()
  })

  it('clearDeviceImageCache', () => {
    saveDeviceImageCache(sample)
    clearDeviceImageCache()
    expect(takeDeviceImageCache()).toBeNull()
  })
})
