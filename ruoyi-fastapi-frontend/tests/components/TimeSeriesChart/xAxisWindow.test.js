import { describe, expect, it } from 'vitest'
import { seriesTimeBounds, visibleYExtent } from '@/components/TimeSeriesChart/seriesTime'
import { clampTimeWindow, createKeepYGuard, liveFollowWindow, startPinnedWindow } from '@/components/TimeSeriesChart/xAxisWindow'
import { curveKey, createColorSlots, MAX_CURVES } from '@/utils/curvePage'

describe('seriesTime', () => {
  it('有序点列只看首末时间', () => {
    const b = seriesTimeBounds([
      { points: [[100, 1], [200, 2], [300, 3]] },
      { points: [[150, 1], [400, 2]] }
    ])
    expect(b.earliest).toBe(100)
    expect(b.latest).toBe(400)
  })

  it('窗口内 Y 范围跳过窗外点', () => {
    const ext = visibleYExtent(
      [{ points: [[0, 10], [50, 99], [100, 20], [200, 30]] }],
      { start: 80, end: 150 }
    )
    expect(ext).toEqual({ min: 20, max: 20 })
  })
})

describe('xAxisWindow', () => {
  it('跟随最新：右端钉在 latest，宽度为窗口', () => {
    const z = liveFollowWindow(0, 10_000, 3000)
    expect(z.endValue).toBe(10_000)
    expect(z.startValue).toBe(7000)
  })

  it('跳到起点：左端钉在 earliest，保持宽度', () => {
    const z = startPinnedWindow(1000, 20_000, 5000)
    expect(z.startValue).toBe(1000)
    expect(z.endValue).toBe(6000)
  })

  it('clamp 不会超出数据两端', () => {
    const z = clampTimeWindow(-100, 99999, 0, 1000)
    expect(z.startValue).toBe(0)
    expect(z.endValue).toBe(1000)
  })

  it('keepY 在本轮内有效，schedule 后清掉，不会粘住', () => {
    const pending = []
    const guard = createKeepYGuard(fn => pending.push(fn))
    guard.begin()
    expect(guard.active()).toBe(true)
    guard.begin()
    expect(guard.active()).toBe(true)
    pending.forEach(fn => fn())
    expect(guard.active()).toBe(false)
  })
})

describe('curvePage colors', () => {
  it('curveKey 用 表:字段', () => {
    expect(curveKey('BIU:FF', 'CAMF008')).toBe('BIU:FF:CAMF008')
  })

  it('颜色槽上限与色板长度一致', () => {
    expect(MAX_CURVES).toBe(10)
    const { acquireColor, releaseColor } = createColorSlots()
    const a = acquireColor('a')
    const b = acquireColor('b')
    expect(a).not.toBe(b)
    releaseColor('a')
    expect(acquireColor('a')).toBe(a)
  })
})
