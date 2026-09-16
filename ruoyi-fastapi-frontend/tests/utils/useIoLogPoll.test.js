import { describe, expect, it } from 'vitest'
import { takeIoLogItems } from '@/utils/ioLogSeq'

describe('takeIoLogItems', () => {
  it('增量只收下比水位新的条目', () => {
    const { items, nextSeq } = takeIoLogItems(
      [{ seq: 10 }, { seq: 11 }, { seq: 12 }],
      10
    )
    expect(items.map(i => i.seq)).toEqual([11, 12])
    expect(nextSeq).toBe(12)
  })

  it('水位高于环缓最大序号时整窗接上，避免传输信息假死', () => {
    const { items, nextSeq } = takeIoLogItems([{ seq: 1 }, { seq: 2 }, { seq: 3 }], 9999)
    expect(items.map(i => i.seq)).toEqual([1, 2, 3])
    expect(nextSeq).toBe(3)
  })

  it('已追上时不把同一窗再刷一遍', () => {
    const { items, nextSeq } = takeIoLogItems([{ seq: 1 }, { seq: 2 }, { seq: 5 }], 5)
    expect(items).toEqual([])
    expect(nextSeq).toBe(5)
  })
})
