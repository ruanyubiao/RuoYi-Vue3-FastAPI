import { describe, expect, it } from 'vitest'
import { indexBounds, resolveIndex, resolveRange, sliceBytes } from '@/utils/checksumRange'

describe('utils/checksumRange', () => {
  it('负索引与 Python 一致', () => {
    const data = new Uint8Array([10, 20, 30, 40, 50])
    expect(resolveIndex(-1, 5)).toBe(4)
    expect(resolveIndex(-2, 5)).toBe(3)
    expect(resolveIndex(-3, 5)).toBe(2)
    expect(sliceBytes(data, -1, -1)[0]).toBe(50)
  })

  it('含两端：1~10 共 10 字节', () => {
    const data = new Uint8Array(16)
    const r = resolveRange(1, 10, data.length)
    expect(r).toEqual({ lo: 1, hi: 10 })
    expect(sliceBytes(data, 1, 10).length).toBe(10)
  })

  it('len 越界、等于 len 非法', () => {
    expect(resolveIndex(5, 5)).toBeNull()
    expect(resolveIndex(-6, 5)).toBeNull()
    expect(resolveRange(0, 5, 5)).toBeNull()
  })

  it('默认 0 ~ -1 覆盖全文', () => {
    const data = new Uint8Array([1, 2, 3])
    expect(Array.from(sliceBytes(data, 0, -1))).toEqual([1, 2, 3])
  })

  it('indexBounds', () => {
    expect(indexBounds(5)).toEqual({ min: -5, max: 4 })
    expect(indexBounds(0)).toEqual({ min: -1, max: 0 })
  })
})
