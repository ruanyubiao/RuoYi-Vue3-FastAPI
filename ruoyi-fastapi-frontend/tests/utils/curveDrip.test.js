import { describe, expect, it } from 'vitest'
import {
  CURVE_DRIP_INTERVAL_MS,
  CURVE_POLL_INTERVAL_MS,
  dripBatchSize,
  dripBufferLength,
  dripTicksPerWindow,
  dropFutureCurvePoints,
  incrementalSinceT,
  mergePoints,
  nextFetchCursor,
  reserveSinceT,
  sanitizeSinceT,
  takeDrip,
  takeLiveDrip,
  applyLiveFetch
} from '@/utils/curveDrip'

describe('curveDrip', () => {
  it('一窗拍数至少 1，按当前窗口/间隔计算', () => {
    expect(dripTicksPerWindow()).toBe(Math.ceil(CURVE_POLL_INTERVAL_MS / CURVE_DRIP_INTERVAL_MS))
  })

  it('空缓存每拍为 0', () => {
    expect(dripBatchSize(0)).toBe(0)
    expect(takeDrip([], 10)).toEqual({ chunk: [], buf: [], head: 0 })
  })

  it('按当前全长算出的步长，固定拍数能抽完', () => {
    const ticks = dripTicksPerWindow()
    const total = ticks * 100
    expect(dripBatchSize(total)).toBe(100)
    let buf = Array.from({ length: total }, (_, i) => i)
    let head = 0
    let n = 0
    while (dripBufferLength(buf, head)) {
      const out = takeDrip(buf, 100, head)
      buf = out.buf
      head = out.head
      n += 1
    }
    expect(n).toBe(ticks)
  })

  it('takeDrip 用 head 推进，不 splice 剩余上千点', () => {
    const buf = Array.from({ length: 3000 }, (_, i) => i)
    const out = takeDrip(buf, 100, 0)
    expect(out.chunk).toEqual(Array.from({ length: 100 }, (_, i) => i))
    expect(out.head).toBe(100)
    expect(out.buf.length).toBe(3000)
    expect(out.buf).toBe(buf)
    expect(dripBufferLength(out.buf, out.head)).toBe(2900)
  })

  it('head 较大时才 compact 掉已用前缀', () => {
    const buf = Array.from({ length: 400 }, (_, i) => i)
    const out = takeDrip(buf, 300, 0)
    expect(out.head).toBe(0)
    expect(out.buf[0]).toBe(300)
    expect(out.buf.length).toBe(100)
  })

  it('卡顿剩点又来新点时按全部长度重算', () => {
    const ticks = dripTicksPerWindow()
    const left = 300
    const incoming = 600
    expect(dripBatchSize(left + incoming)).toBe(Math.ceil((left + incoming) / ticks))
  })

  it('积压不丢时间段，从队头按步长上屏', () => {
    const t0 = 1_000_000
    const pending = []
    for (let i = 0; i < 20000; i++) pending.push([t0 + i, i])
    const out = takeLiveDrip(pending, 0, { batch: 100, maxLagMs: 400 })
    expect(out.chunk[0][0]).toBe(t0)
    expect(out.chunk).toHaveLength(100)
    expect(out.chunk[99][0]).toBe(t0 + 99)
  })

  it('sinceT 用已拉取最大 t，不会退回到更早的上屏时间', () => {
    expect(nextFetchCursor(1789440575923, [[1789440750943, 1]])).toBe(1789440750943)
    expect(nextFetchCursor(1789440750943, [])).toBe(1789440750943)
    expect(nextFetchCursor(1789440750943, [[1789440575923, 1]])).toBe(1789440750943)
    expect(nextFetchCursor(100, [[300, 1], [200, 1]])).toBe(300)
  })

  it('增量 sinceT 按本条末点，两条曲线可以不同', () => {
    expect(incrementalSinceT({ fetchCursorT: 2216, points: [[2672, 1]] })).toBe(2672)
    expect(incrementalSinceT({ fetchCursorT: 2216, points: [[2713, 1]] })).toBe(2713)
    expect(incrementalSinceT({ fetchCursorT: 2216, points: [[7502, 1], [7609, 1], [7400, 1]] })).toBe(7609)
  })

  it('已发出的 sinceT 不会被后到的更小水位打回去', () => {
    expect(reserveSinceT(7609, 7502)).toBe(7609)
    expect(reserveSinceT(undefined, 7502)).toBe(7502)
    expect(reserveSinceT(7609, null)).toBe(7609)
  })

  it('未来 sinceT 丢弃，增量改拉墙钟点', () => {
    const now = Date.now()
    const future = now + 60_000
    expect(sanitizeSinceT(future, now)).toBeNull()
    expect(sanitizeSinceT(now - 1000, now)).toBe(now - 1000)
    expect(nextFetchCursor(future, [[now - 10, 1]], now)).toBe(now - 10)
    expect(incrementalSinceT({ fetchCursorT: future, points: [[now - 20, 1]] }, now)).toBe(now - 20)
    expect(dropFutureCurvePoints([[future, 9], [now - 5, 1]], now)).toEqual([[now - 5, 1]])
  })

  it('增量点晚于末点时只拼接，重叠时才全量合并', () => {
    const existing = [[1, 1], [2, 2], [3, 3]]
    expect(mergePoints(existing, [[4, 4], [5, 5]], 10)).toEqual([
      [1, 1], [2, 2], [3, 3], [4, 4], [5, 5]
    ])
    expect(mergePoints(existing, [[2, 20], [4, 4]], 10)).toEqual([
      [1, 1], [2, 20], [3, 3], [4, 4]
    ])
    const cap = mergePoints(
      Array.from({ length: 5 }, (_, i) => [i, i]),
      [[5, 5], [6, 6]],
      5
    )
    expect(cap).toEqual([[2, 2], [3, 3], [4, 4], [5, 5], [6, 6]])
  })

  it('按本轮新点数定步长，小于按积压全长定步长', () => {
    expect(dripBatchSize(20)).toBeLessThan(dripBatchSize(80))
  })

  it('本轮拉取为空时剩余缓存一次性上屏，不再按 1 点/拍空转', () => {
    const pending = Array.from({ length: 6000 }, (_, i) => [i, i])
    const out = applyLiveFetch(pending, [], 20000)
    expect(out.pending).toEqual([])
    expect(out.flush).toBe(pending)
    const ticksIfDripOne = out.flush.length
    expect(ticksIfDripOne * CURVE_DRIP_INTERVAL_MS).toBeGreaterThan(60_000)
  })

  it('本轮有新点时仍进缓存，不上屏', () => {
    const pending = [[1, 1], [2, 2]]
    const incoming = [[3, 3], [4, 4]]
    const out = applyLiveFetch(pending, incoming, 20000)
    expect(out.flush).toEqual([])
    expect(out.pending).toEqual([[1, 1], [2, 2], [3, 3], [4, 4]])
  })
})
