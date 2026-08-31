import { describe, expect, it, vi } from 'vitest'
import cache from '@/plugins/cache'

describe('cache.expire', () => {
  it('API 与 local 同名：set/get/setJSON/getJSON/remove', () => {
    expect(cache.expire).toBeDefined()
    expect(typeof cache.expire.set).toBe('function')
    expect(typeof cache.expire.get).toBe('function')
    expect(typeof cache.expire.setJSON).toBe('function')
    expect(typeof cache.expire.getJSON).toBe('function')
    expect(typeof cache.expire.remove).toBe('function')
  })

  it('set/get：第三参数为过期秒数', () => {
    vi.useFakeTimers()
    cache.expire.set('ttl-k', 'v', 2)
    expect(cache.expire.get('ttl-k')).toBe('v')
    vi.advanceTimersByTime(2001)
    expect(cache.expire.get('ttl-k')).toBeNull()
    expect(localStorage.getItem('ttl-k')).toBeNull()
    vi.useRealTimers()
  })

  it('无 exp 时不过期', () => {
    cache.expire.set('forever', 'ok')
    expect(cache.expire.get('forever')).toBe('ok')
  })

  it('setJSON/getJSON 往返', () => {
    cache.expire.setJSON('obj', { x: 1 }, 60)
    expect(cache.expire.getJSON('obj')).toEqual({ x: 1 })
  })

  it('getJSON 无键或过期返回 defaultValue', () => {
    expect(cache.expire.getJSON('missing', { a: 1 })).toEqual({ a: 1 })
    vi.useFakeTimers()
    cache.expire.setJSON('soon', { a: 1 }, 1)
    vi.advanceTimersByTime(1001)
    expect(cache.expire.getJSON('soon', {})).toEqual({})
    vi.useRealTimers()
  })

  it('get 过期返回 defaultValue', () => {
    vi.useFakeTimers()
    cache.expire.set('k', 'v', 1)
    vi.advanceTimersByTime(1001)
    expect(cache.expire.get('k', 'fallback')).toBe('fallback')
    vi.useRealTimers()
  })

  it('remove 删除键', () => {
    cache.expire.set('rm', '1', 60)
    cache.expire.remove('rm')
    expect(cache.expire.get('rm')).toBeNull()
  })

  it('value 为 null/undefined 时删除', () => {
    cache.expire.set('d', '1', 60)
    cache.expire.set('d', null)
    expect(cache.expire.get('d')).toBeNull()
  })

  it('keys 按前缀列出未过期项的存储键', () => {
    cache.expire.set('payload:ttl:a', '1', 60)
    cache.expire.set('payload:ttl:b', '2', 60)
    cache.local.set('payload:keep', 'x')
    expect(cache.expire.keys('payload:ttl:').sort()).toEqual(['payload:ttl:a', 'payload:ttl:b'])
  })
})
