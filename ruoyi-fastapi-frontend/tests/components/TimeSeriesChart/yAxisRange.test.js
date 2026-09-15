import { describe, expect, it } from 'vitest'
import { alignedYInterval, displayYRange, formatYTick, niceYRange, nudgeYMax, nudgeYMin, panYRange, stabilizeYRange, Y_ZOOM_IN, Y_ZOOM_OUT, zoomYCenter, zoomYRange } from '@/components/TimeSeriesChart/yAxisRange'

describe('yAxisRange', () => {
  it('把数据范围收成整齐刻度', () => {
    const r = niceYRange(2421.8, 2439)
    expect(r.interval).toBeGreaterThan(0)
    expect(r.min).toBeLessThanOrEqual(2421.8)
    expect(r.max).toBeGreaterThanOrEqual(2439)
    expect((r.max - r.min) / r.interval).toBeGreaterThanOrEqual(2)
    expect(r.min / r.interval).toBeCloseTo(Math.round(r.min / r.interval), 6)
    expect(alignedYInterval(r.min, r.max, r.interval)).toBe(r.interval)
  })

  it('数据仍在轴内时不改 min/max，避免横线跳动', () => {
    const cur = { min: 2420, max: 2440, interval: 5 }
    expect(stabilizeYRange(cur, 2424, 2436)).toBe(cur)
  })

  it('数据越出当前轴时才重算', () => {
    const cur = { min: 2420, max: 2440, interval: 5 }
    const next = stabilizeYRange(cur, 2424, 2450)
    expect(next).not.toBe(cur)
    expect(next.max).toBeGreaterThanOrEqual(2450)
  })

  it('滚轮缩放忽略超出当前轴的 pivot，避免刻度炸成乱序大数', () => {
    const cur = { min: 2160, max: 2200 }
    const next = zoomYRange(cur, Y_ZOOM_IN, 1_760_000_000_000)
    expect(next.min).toBeGreaterThan(2160)
    expect(next.max).toBeLessThan(2200)
    expect(next.max).toBeGreaterThan(next.min)
    expect(Math.abs((next.min + next.max) / 2 - 2180)).toBeLessThan(1)
  })

  it('连续滚轮缩放后 min/max 仍有序且不会发散', () => {
    let r = { min: 2160, max: 2200 }
    for (let i = 0; i < 40; i++) r = zoomYRange(r, i % 3 === 0 ? Y_ZOOM_OUT : Y_ZOOM_IN, 2181)
    expect(r.max).toBeGreaterThan(r.min)
    expect(r.max - r.min).toBeGreaterThan(0)
    expect(r.max).toBeLessThan(1e8)
    expect(r.min).toBeGreaterThan(-1e8)
  })

  it('不对齐的 interval 不交给 ECharts', () => {
    expect(alignedYInterval(2171.3, 2193.8, (2193.8 - 2171.3) / 5)).toBeNull()
    expect(alignedYInterval(2160, 2200, 5)).toBe(5)
  })

  it('顶底端点收成整齐刻度，避免 2660.00763363 被裁成 00763363', () => {
    const shown = displayYRange({ min: 2583.00763357, max: 2667.00763363 })
    expect(shown.interval).toBeGreaterThan(0)
    expect(shown.min).toBe(Math.round(shown.min / shown.interval) * shown.interval)
    expect(shown.max).toBe(Math.round(shown.max / shown.interval) * shown.interval)
    expect(formatYTick(2660.00763363, 20)).toBe('')
    expect(formatYTick(2660, 20)).toBe('2660')
    expect(formatYTick(2600, 20)).toBe('2600')
  })

  it('Y轴上移半格：刻度间距1000则移动500，最大值变小', () => {
    const next = panYRange({ min: 1000, max: 5000, interval: 1000 }, 1)
    expect(next).toEqual({ min: 500, max: 4500, interval: 1000 })
    expect(alignedYInterval(next.min, next.max, next.interval)).toBe(1000)
    expect(formatYTick(4500, 1000)).toBe('4500')
    expect(formatYTick(500, 1000)).toBe('500')
  })

  it('Y轴下移半格：最大值变大', () => {
    const next = panYRange({ min: 1000, max: 5000, interval: 1000 }, -1)
    expect(next).toEqual({ min: 1500, max: 5500, interval: 1000 })
  })

  it('改最大值：+放大 -缩小，步长为刻度间距一半', () => {
    const base = { min: 1000, max: 5000, interval: 1000 }
    expect(nudgeYMax(base, 1)).toEqual({ min: 1000, max: 5500, interval: 1000 })
    expect(nudgeYMax(base, -1)).toEqual({ min: 1000, max: 4500, interval: 1000 })
    expect(alignedYInterval(1000, 4500, 1000)).toBe(1000)
  })

  it('改最小值：+变大 -变小，步长为刻度间距一半', () => {
    const base = { min: 1000, max: 5000, interval: 1000 }
    expect(nudgeYMin(base, 1)).toEqual({ min: 1500, max: 5000, interval: 1000 })
    expect(nudgeYMin(base, -1)).toEqual({ min: 500, max: 5000, interval: 1000 })
  })

  it('以轴中点放大后范围必须变窄，不能被整齐刻度吸回原范围', () => {
    const base = { min: 1000, max: 5000, interval: 1000 }
    const next = zoomYCenter(base, Y_ZOOM_IN)
    expect(next.max - next.min).toBeLessThan(4000)
    expect(next.max).toBeGreaterThan(next.min)
    expect(Math.abs((next.min + next.max) / 2 - 3000)).toBeLessThan(base.interval)
    expect(alignedYInterval(next.min, next.max, next.interval)).toBe(next.interval)
  })
})
