import { describe, expect, it } from 'vitest'
import { resetTransportRequestConfig, shouldRetryTransportWithFreshKey } from '@/utils/transportCrypto'

describe('utils/transportCrypto', () => {
  it('shouldRetryTransportWithFreshKey 识别可重试错误', () => {
    expect(shouldRetryTransportWithFreshKey({ message: 'Decryption failed' })).toBe(true)
    expect(shouldRetryTransportWithFreshKey({ response: { data: { msg: '密钥版本不存在' } } })).toBe(true)
    expect(shouldRetryTransportWithFreshKey({ message: 'network error' })).toBe(false)
  })

  it('resetTransportRequestConfig 恢复原始请求', () => {
    const config = {
      url: '/encrypted',
      params: { a: 1 },
      data: { x: 2 },
      headers: { 'Content-Type': 'application/json' },
      __transportOriginalSnapshot: {
        url: '/plain',
        params: { b: 2 },
        data: 'raw',
        contentType: 'text/plain'
      },
      __transportCryptoContext: {},
      __transportCryptoEnabledForRequest: true
    }
    const restored = resetTransportRequestConfig(config)
    expect(restored.url).toBe('/plain')
    expect(restored.params).toEqual({ b: 2 })
    expect(restored.data).toBe('raw')
    expect(restored.headers['Content-Type']).toBe('text/plain')
    expect(restored.__transportCryptoContext).toBeUndefined()
    expect(restored.__transportCryptoEnabledForRequest).toBeUndefined()
  })

  it('无 snapshot 时原样返回', () => {
    const config = { url: '/x' }
    expect(resetTransportRequestConfig(config)).toBe(config)
  })
})
