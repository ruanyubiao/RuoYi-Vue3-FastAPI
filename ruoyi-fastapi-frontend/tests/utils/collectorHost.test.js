import { describe, expect, it } from 'vitest'
import { findCollectorDevice, pickCollectorHost } from '@/utils/collectorHost'

describe('findCollectorDevice', () => {
  const data = {
    devices: [
      { host: 'box-a', online: true },
      { host: 'box-b', online: false }
    ]
  }

  it('没点名时用第一台在线的', () => {
    expect(findCollectorDevice(data, '').host).toBe('box-a')
  })

  it('点名离线机时留在这一台', () => {
    const row = findCollectorDevice(data, 'box-b')
    expect(row.host).toBe('box-b')
    expect(row.online).toBe(false)
  })
})

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
