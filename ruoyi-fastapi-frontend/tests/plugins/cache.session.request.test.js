import { describe, expect, it } from 'vitest'
import cache from '@/plugins/cache'

/**
 * request.js 防重复提交依赖 cache.session 的 sessionObj。
 * 此处锁定读写契约，不拉 axios/router。
 */
describe('cache.session 防重复提交契约', () => {
  it('setJSON/getJSON sessionObj', () => {
    const requestObj = { url: '/payload/device/can/open', data: '{"vendor":0}', time: 1000 }
    cache.session.setJSON('sessionObj', requestObj)
    expect(cache.session.getJSON('sessionObj')).toEqual(requestObj)
  })

  it('相同 url+data 在 interval 内可判定为重复', () => {
    const first = { url: '/a', data: '{}', time: 1000 }
    cache.session.setJSON('sessionObj', first)
    const sessionObj = cache.session.getJSON('sessionObj')
    const next = { url: '/a', data: '{}', time: 1400 }
    const interval = 500
    const isDup =
      sessionObj.data === next.data && next.time - sessionObj.time < interval && sessionObj.url === next.url
    expect(isDup).toBe(true)
  })

  it('getJSON 无键返回 null（与 request 判断一致）', () => {
    expect(cache.session.getJSON('sessionObj')).toBeNull()
  })
})
