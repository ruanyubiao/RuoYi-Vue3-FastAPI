import { describe, expect, it } from 'vitest'
import {
  getTransportCryptoPolicy,
  invalidateTransportCryptoPolicy,
  shouldEncryptQuery,
  shouldEncryptRequest,
  shouldEncryptResponse
} from '@/utils/transportCryptoPolicy'

const activePolicy = {
  transportCryptoActive: true,
  enabledPaths: ['/payload'],
  excludePaths: ['/common/download'],
  maxEncryptedGetUrlLength: 4096
}

describe('utils/transportCryptoPolicy', () => {
  it('getTransportCryptoPolicy 默认明文回退', () => {
    invalidateTransportCryptoPolicy()
    const p = getTransportCryptoPolicy()
    expect(p.transportCryptoActive).toBe(false)
    expect(p.excludePaths.length).toBeGreaterThan(0)
  })

  it('transportCryptoActive=false 不加密', () => {
    const policy = { ...activePolicy, transportCryptoActive: false }
    expect(shouldEncryptRequest({ url: '/payload/device' }, policy)).toBe(false)
    expect(shouldEncryptResponse({ url: '/payload/device' }, policy)).toBe(false)
  })

  it('excludePaths 与固定排除 URL', () => {
    expect(shouldEncryptRequest({ url: '/common/download' }, activePolicy)).toBe(false)
    expect(shouldEncryptRequest({ url: '/transport/crypto/public-key' }, activePolicy)).toBe(false)
    expect(shouldEncryptRequest({ url: '/payload/x' }, { ...activePolicy, excludePaths: ['/payload'] })).toBe(
      false
    )
  })

  it('enabledPaths 白名单', () => {
    expect(shouldEncryptRequest({ url: '/payload/device' }, activePolicy)).toBe(true)
    expect(shouldEncryptRequest({ url: '/system/user' }, activePolicy)).toBe(false)
  })

  it('headers 可关闭加密', () => {
    expect(
      shouldEncryptRequest({ url: '/payload/x', headers: { encrypt: false } }, activePolicy)
    ).toBe(false)
    expect(
      shouldEncryptResponse({ url: '/payload/x', headers: { encryptResponse: false } }, activePolicy)
    ).toBe(false)
    expect(
      shouldEncryptQuery({ url: '/payload/x', headers: { encryptQuery: false } }, activePolicy)
    ).toBe(false)
  })

  it('blob/multipart 不加密请求', () => {
    expect(shouldEncryptRequest({ url: '/payload/x', responseType: 'blob' }, activePolicy)).toBe(false)
    expect(
      shouldEncryptRequest(
        { url: '/payload/x', headers: { 'Content-Type': 'multipart/form-data' } },
        activePolicy
      )
    ).toBe(false)
  })

  it('__transportCryptoEnabledForRequest 控制响应解密', () => {
    const inactive = { ...activePolicy, transportCryptoActive: false }
    expect(shouldEncryptResponse({ url: '/payload/x', __transportCryptoEnabledForRequest: true }, inactive)).toBe(
      true
    )
    expect(shouldEncryptResponse({ url: '/payload/x', __transportCryptoEnabledForRequest: false }, activePolicy)).toBe(
      false
    )
  })
})
