import { describe, expect, it } from 'vitest'
import { fillDefaults, normalizeRecord } from '@/plugins/cache'

describe('fillDefaults', () => {
  it('raw 缺字段用 defaults 补上', () => {
    expect(fillDefaults({ a: 1 }, { a: 0, b: 2 })).toEqual({ a: 1, b: 2 })
  })

  it('raw 为 null 返回 defaults 拷贝', () => {
    const defaults = { tmType: '' }
    expect(fillDefaults(null, defaults)).toEqual({ tmType: '' })
  })

  it('null 值保留（不当成缺失）', () => {
    expect(fillDefaults({ a: null }, { a: 1, b: 2 })).toEqual({ a: null, b: 2 })
  })
})

describe('normalizeRecord', () => {
  const spec = {
    src: v => String(v || ''),
    width: v => Number(v) || 0,
    height: v => Number(v) || 0,
    imageNo: v => v ?? null,
    refreshTime: v => v || ''
  }

  it('按 spec 转换字段', () => {
    expect(
      normalizeRecord({ src: 'data:x', width: '64' }, spec, { src: '', width: 0, height: 0, imageNo: null, refreshTime: '' })
    ).toEqual({
      src: 'data:x',
      width: 64,
      height: 0,
      imageNo: null,
      refreshTime: ''
    })
  })
})
