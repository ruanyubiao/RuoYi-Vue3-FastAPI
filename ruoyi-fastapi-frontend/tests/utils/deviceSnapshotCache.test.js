import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@/api/payload/device', () => ({
  getDeviceSnapshot: vi.fn()
}))

import {
  invalidateDeviceSnapshot,
  saveDeviceSnapshot,
  setActiveDevice,
  getActiveDevice,
  clearActiveDevice,
  takeDeviceSnapshot
} from '@/utils/deviceSnapshotCache'

describe('utils/deviceSnapshotCache', () => {
  beforeEach(() => {
    invalidateDeviceSnapshot()
  })
  it('save / take 快照合并', () => {
    saveDeviceSnapshot({ can: [{ id: 1 }] })
    saveDeviceSnapshot({ serialList: ['COM1'] })
    const data = takeDeviceSnapshot()
    expect(data?.can).toEqual([{ id: 1 }])
    expect(data?.serialList).toEqual(['COM1'])
  })

  it('invalidate 清空', () => {
    saveDeviceSnapshot({ parsers: [] })
    invalidateDeviceSnapshot()
    expect(takeDeviceSnapshot()).toBeNull()
  })

  it('consume 读取后删除', () => {
    saveDeviceSnapshot({ a: 1 })
    expect(takeDeviceSnapshot({ consume: true })?.a).toBe(1)
    expect(takeDeviceSnapshot()).toBeNull()
  })

  it('活动设备 id 带 TTL', () => {
    setActiveDevice('can', 'can:0:0:0')
    expect(getActiveDevice('can')).toBe('can:0:0:0')
    clearActiveDevice('can')
    expect(getActiveDevice('can')).toBe('')
  })

  it('兼容旧版纯字符串活动设备', () => {
    localStorage.setItem('payload:activeDeviceId', 'legacy-id')
    expect(getActiveDevice('can')).toBe('legacy-id')
    clearActiveDevice('can')
  })
})
