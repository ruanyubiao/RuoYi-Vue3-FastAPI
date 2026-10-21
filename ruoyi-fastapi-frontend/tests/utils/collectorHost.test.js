import { describe, expect, it } from 'vitest'
import { pickCollectorHost } from '@/utils/collectorHost'

describe('pickCollectorHost', () => {
  const collectors = [{ host: 'box-a' }, { host: 'box-b' }]

  it('已保存的标识仍在列表里时保持不动', () => {
    expect(pickCollectorHost('box-b', 'local', collectors)).toBe('box-b')
  })

  it('默认 local 不在列表里时选第一项', () => {
    expect(pickCollectorHost('local', 'local', collectors)).toBe('box-a')
    expect(pickCollectorHost('', 'local', collectors)).toBe('box-a')
  })

  it('一台都没有时仍用 local', () => {
    expect(pickCollectorHost('local', 'local', [])).toBe('local')
    expect(pickCollectorHost('', '', [])).toBe('local')
    expect(pickCollectorHost('gk3', 'local', [])).toBe('local')
  })
})
