import { describe, expect, it } from 'vitest'
import { isEmpty, isExternal, isHttp, isPathMatch } from '@/utils/validate'

describe('utils/validate', () => {
  it('isPathMatch 通配', () => {
    expect(isPathMatch('/system/*', '/system/user')).toBe(true)
    expect(isPathMatch('/system/*', '/monitor/job')).toBe(false)
  })

  it('isEmpty', () => {
    expect(isEmpty('')).toBe(true)
    expect(isEmpty(null)).toBe(true)
    expect(isEmpty('x')).toBe(false)
  })

  it('isHttp / isExternal', () => {
    expect(isHttp('https://a.com')).toBe(true)
    expect(isHttp('/local')).toBe(false)
    expect(isExternal('mailto:a@b.com')).toBe(true)
    expect(isExternal('/index')).toBe(false)
  })
})
