import { describe, expect, it, vi } from 'vitest'
import { byteLength, cleanArray, deepClone, formatDate, formatTime, getQueryObject, isNumberStr, param } from '@/utils/index'

describe('utils/index', () => {
  it('formatDate 空值', () => {
    expect(formatDate(null)).toBe('')
    expect(formatDate('')).toBe('')
  })

  it('formatDate 格式化', () => {
    expect(formatDate('2021-01-02T03:04:05')).toMatch(/^2021-01-02 03:04:05$/)
  })

  it('formatTime 相对时间', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2021-01-02T12:00:00'))
    const ts = new Date('2021-01-02T11:59:50').getTime()
    expect(formatTime(ts)).toBe('刚刚')
    vi.useRealTimers()
  })

  it('getQueryObject 解析 query', () => {
    const obj = getQueryObject('http://x.test/a?foo=1&bar=hello%20world')
    expect(obj.foo).toBe('1')
    expect(obj.bar).toBe('hello world')
  })

  it('byteLength UTF-8', () => {
    expect(byteLength('abc')).toBe(3)
    expect(byteLength('中文')).toBe(6)
  })

  it('cleanArray 去 falsy', () => {
    expect(cleanArray([0, 1, false, 2, '', 3])).toEqual([1, 2, 3])
  })

  it('deepClone 独立副本', () => {
    const src = { a: [1], b: { c: 2 } }
    const copy = deepClone(src)
    copy.a.push(2)
    copy.b.c = 9
    expect(src.a).toEqual([1])
    expect(src.b.c).toBe(2)
  })

  it('param / isNumberStr', () => {
    expect(param({ a: 1, b: undefined })).toBe('a=1')
    expect(isNumberStr('12')).toBe(true)
    expect(isNumberStr('12a')).toBe(false)
  })
})
