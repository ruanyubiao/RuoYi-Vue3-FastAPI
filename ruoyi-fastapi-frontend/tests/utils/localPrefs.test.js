import { describe, expect, it } from 'vitest'
import cache from '@/plugins/cache'

/** 原 localPrefs 语义已并入 cache.local */
describe('cache.local（原 localPrefs 行为）', () => {
  it('get 无值返回 default', () => {
    expect(cache.local.get('nope', 'def')).toBe('def')
  })

  it('set 空串保留；null 删除', () => {
    cache.local.set('s', 'hello')
    expect(cache.local.get('s')).toBe('hello')
    cache.local.set('s', null)
    expect(cache.local.get('s')).toBeNull()
  })

  it('setJSON / getJSON', () => {
    cache.local.setJSON('j', { tmType: 'XL:FF' })
    expect(cache.local.getJSON('j')).toEqual({ tmType: 'XL:FF' })
  })

  it('getJSON 非法 JSON 返回 default', () => {
    localStorage.setItem('bad', '{not json')
    expect(cache.local.getJSON('bad', {})).toEqual({})
  })

  it('setJSON null 删除键', () => {
    cache.local.setJSON('del', { x: 1 })
    cache.local.setJSON('del', null)
    expect(cache.local.getJSON('del')).toBeNull()
  })

  it('整数以字符串存取', () => {
    cache.local.set('n', String(Math.trunc(13)))
    expect(Number.parseInt(cache.local.get('n'), 10)).toBe(13)
    cache.local.remove('n')
    expect(cache.local.get('n', '0')).toBe('0')
  })
})
