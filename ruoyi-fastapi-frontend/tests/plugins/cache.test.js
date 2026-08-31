import { describe, expect, it } from 'vitest'
import cache from '@/plugins/cache'

describe('plugins/cache', () => {
  describe('cache.local', () => {
    it('set/get 字符串', () => {
      cache.local.set('k1', 'v1')
      expect(cache.local.get('k1')).toBe('v1')
    })

    it('setJSON/getJSON 对象', () => {
      cache.local.setJSON('obj', { a: 1, b: 'x' })
      expect(cache.local.getJSON('obj')).toEqual({ a: 1, b: 'x' })
    })

    it('getJSON 无键返回 null，可传 defaultValue', () => {
      expect(cache.local.getJSON('missing')).toBeNull()
      expect(cache.local.getJSON('missing', {})).toEqual({})
    })

    it('getJSON 非法 JSON 返回 defaultValue', () => {
      localStorage.setItem('bad', '{not json')
      expect(cache.local.getJSON('bad', { ok: 1 })).toEqual({ ok: 1 })
    })

    it('remove 删除键', () => {
      cache.local.set('rm', '1')
      cache.local.remove('rm')
      expect(cache.local.get('rm')).toBeNull()
    })

    it('keys 按前缀列出', () => {
      cache.local.set('payload:a:v1', '1')
      cache.local.set('payload:b:v1', '2')
      cache.local.set('other', '3')
      expect(cache.local.keys('payload:').sort()).toEqual(['payload:a:v1', 'payload:b:v1'])
    })
  })

  describe('cache.session', () => {
    it('set/get 与会话隔离', () => {
      cache.session.set('sk', 'sv')
      expect(cache.session.get('sk')).toBe('sv')
      expect(cache.local.get('sk')).toBeNull()
    })

    it('setJSON/getJSON', () => {
      cache.session.setJSON('flag', { needRefresh: true })
      expect(cache.session.getJSON('flag')).toEqual({ needRefresh: true })
    })
  })
})
