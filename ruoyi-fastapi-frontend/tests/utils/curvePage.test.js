import { describe, expect, it } from 'vitest'
import { buildChartSeries, paintSeriesPoints } from '@/utils/curvePage'

describe('curvePage live paint', () => {
  it('显式 bucketMs 才合桶，顶点随桶宽上界', () => {
    const pts = Array.from({ length: 20000 }, (_, i) => [i, i % 9])
    const out = paintSeriesPoints(pts, { start: 0, end: 20000, pixelWidth: 800, bucketMs: 25 })
    expect(out.length).toBeGreaterThan(0)
    expect(out.length).toBeLessThanOrEqual(1602)
    expect(out.length).toBeLessThan(pts.length)
  })

  it('未给 bucketMs 时原样上屏，不重抽历史点', () => {
    const pts = [[1, 1], [2, 2], [3, 3]]
    expect(paintSeriesPoints(pts, { start: 1, end: 3, pixelWidth: 800 })).toBe(pts)
  })

  it('buildChartSeries 无 bucketMs 时用缓存原样，缓存点数不变', () => {
    const pts = Array.from({ length: 5000 }, (_, i) => [i, i === 2500 ? 99 : 1])
    const curves = [{ key: 'T:A', field: 'A', name: 'a', color: '#000', points: pts }]
    const series = buildChartSeries(curves, { start: 0, end: 5000, pixelWidth: 200 })
    expect(pts).toHaveLength(5000)
    expect(series[0].data).toBe(pts)
    expect(series[0].data.some(p => p[1] === 99)).toBe(true)
  })

  it('合桶覆盖全量时间，不按当前视窗裁掉两端', () => {
    const pts = Array.from({ length: 10000 }, (_, i) => [i, 1])
    const out = paintSeriesPoints(pts, { start: 8000, end: 9000, pixelWidth: 100, bucketMs: 10 })
    expect(out[0][0]).toBeLessThan(8000)
    expect(out[out.length - 1][0]).toBeGreaterThan(9000)
  })

  it('追加新点不改写已上屏历史顶点', () => {
    const hist = Array.from({ length: 8000 }, (_, i) => [i, i % 5 === 0 ? 9 : 1])
    const paint = { start: 0, end: 8000, pixelWidth: 400 }
    const a = paintSeriesPoints(hist, paint)
    const extra = Array.from({ length: 2000 }, (_, i) => [8000 + i, 1])
    const b = paintSeriesPoints(hist.concat(extra), { ...paint, end: 10000 })
    const key = p => `${p[0]},${p[1]}`
    const leftA = a.filter(p => p[0] <= 7000).map(key)
    const leftB = b.filter(p => p[0] <= 7000).map(key)
    expect(leftB).toEqual(leftA)
  })

  it('固定 bucketMs 合桶时，追加新点也不挪历史峰', () => {
    const hist = Array.from({ length: 8000 }, (_, i) => [i, i % 5 === 0 ? 9 : 1])
    const paint = { bucketMs: 20, pixelWidth: 400 }
    const a = paintSeriesPoints(hist, paint)
    const extra = Array.from({ length: 2000 }, (_, i) => [8000 + i, 1])
    const b = paintSeriesPoints(hist.concat(extra), paint)
    const key = p => `${p[0]},${p[1]}`
    const leftA = a.filter(p => p[0] <= 7000).map(key)
    const leftB = b.filter(p => p[0] <= 7000).map(key)
    expect(leftB).toEqual(leftA)
  })
})
