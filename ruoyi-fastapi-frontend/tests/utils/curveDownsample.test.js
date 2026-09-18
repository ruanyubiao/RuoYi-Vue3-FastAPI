import { describe, expect, it } from 'vitest'
import {
  downsampleMinMax,
  downsampleWindowMinMax,
  downsampleWindowSize
} from '@/utils/curveDownsample'

describe('curveDownsample', () => {
  it('倍率 10 对应 20 点窗口', () => {
    expect(downsampleWindowSize(10)).toBe(20)
    expect(downsampleWindowSize(1000)).toBe(2000)
    expect(downsampleWindowSize(0)).toBe(0)
    expect(downsampleWindowSize(1)).toBe(0)
  })

  it('全量不抽稀', () => {
    const pts = [[1, 1], [2, 2], [3, 3]]
    expect(downsampleMinMax(pts, 0)).toBe(pts)
    expect(downsampleMinMax(pts, 1)).toBe(pts)
  })

  it('窗口保留峰谷，按时间排序', () => {
    const chunk = [
      [1, 3],
      [2, 9],
      [3, 1],
      [4, 5]
    ]
    expect(downsampleWindowMinMax(chunk)).toEqual([
      [2, 9],
      [3, 1]
    ])
  })

  it('等值只留时间更早的点', () => {
    const chunk = [
      [1, 4],
      [2, 4],
      [3, 4]
    ]
    expect(downsampleWindowMinMax(chunk)).toEqual([[1, 4]])
  })

  it('单点窗口原样保留', () => {
    expect(downsampleWindowMinMax([[9, 1.5]])).toEqual([[9, 1.5]])
  })

  it('末窗不足 2N 也抽稀', () => {
    const pts = []
    for (let i = 0; i < 25; i++) pts.push([i, i % 5 === 0 ? 10 : 1])
    const out = downsampleMinMax(pts, 10)
    expect(out.length).toBeGreaterThan(0)
    expect(out.length).toBeLessThan(pts.length)
    expect(out[out.length - 1][0]).toBeGreaterThanOrEqual(20)
  })
})
