import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  logout: vi.fn(),
  removeToken: vi.fn(),
  message: vi.fn(),
  confirm: vi.fn(() => new Promise(() => {}))
}))

vi.mock('@/router', () => ({ default: { push: vi.fn() } }))
vi.mock('@/api/login', () => ({ login: vi.fn(), logout: mocks.logout, getInfo: vi.fn() }))
vi.mock('@/utils/auth', () => ({ getToken: vi.fn(() => 'old-token'), setToken: vi.fn(), removeToken: mocks.removeToken }))
vi.mock('element-plus', () => ({
  ElMessage: mocks.message,
  ElMessageBox: { confirm: mocks.confirm },
  ElNotification: { error: vi.fn() },
  ElLoading: { service: vi.fn() }
}))
vi.mock('@/utils/transportCrypto', () => ({
  decryptTransportErrorResponse: async error => error,
  decryptTransportResponse: async res => res,
  encryptTransportRequest: async config => config,
  invalidateTransportKeyMeta: vi.fn(),
  resetTransportRequestConfig: config => config,
  shouldRetryTransportWithFreshKey: () => false
}))

const { default: useUserStore } = await import('@/store/modules/user')
const { default: service, isInvalidTokenMessage, isRelogin } = await import('@/utils/request')

const onFulfilled = service.interceptors.response.handlers[0].fulfilled
const onRejected = service.interceptors.response.handlers[0].rejected

const okResponse = (data, url = '/getInfo') => ({ data, config: { url }, request: { responseType: '' } })

function stubLocation(pathname) {
  const loc = { pathname, href: pathname }
  vi.stubGlobal('location', loc)
  return loc
}

describe('token无法解析时清除本地token', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.unstubAllGlobals()
    isRelogin.show = false
    const store = useUserStore()
    store.token = 'old-token'
    store.roles = ['admin']
    store.permissions = ['*:*:*']
  })

  it('识别 PyJWT 解析失败信息', () => {
    expect(isInvalidTokenMessage('Signature verification failed')).toBe(true)
    expect(isInvalidTokenMessage('Not enough segments')).toBe(true)
    expect(isInvalidTokenMessage('Invalid header padding')).toBe(true)
    expect(isInvalidTokenMessage('Invalid payload padding')).toBe(true)
    expect(isInvalidTokenMessage('用户名或密码错误')).toBe(false)
    expect(isInvalidTokenMessage(undefined)).toBe(false)
  })

  it('logOut 退出接口失败时仍清除本地状态并 resolve', async () => {
    mocks.logout.mockRejectedValue(new Error('Signature verification failed'))
    const store = useUserStore()
    await expect(store.logOut()).resolves.toBeUndefined()
    expect(mocks.logout).toHaveBeenCalledOnce()
    expect(store.token).toBe('')
    expect(store.roles).toEqual([])
    expect(store.permissions).toEqual([])
    expect(mocks.removeToken).toHaveBeenCalledOnce()
  })

  it('logOut 退出接口成功时清除本地状态', async () => {
    mocks.logout.mockResolvedValue({ code: 200 })
    const store = useUserStore()
    await store.logOut()
    expect(store.token).toBe('')
    expect(mocks.removeToken).toHaveBeenCalledOnce()
  })

  it('code 500 + Signature verification failed：清除token、提示一次并跳转，不调用退出接口', async () => {
    const loc = stubLocation('/system/user')
    const res = okResponse({ code: 500, msg: 'Signature verification failed' })
    await expect(onFulfilled(res)).rejects.toThrow('Signature verification failed')
    await expect(onFulfilled(res)).rejects.toThrow('Signature verification failed')
    expect(useUserStore().token).toBe('')
    expect(mocks.removeToken).toHaveBeenCalledTimes(2)
    expect(mocks.message).toHaveBeenCalledOnce()
    expect(mocks.logout).not.toHaveBeenCalled()
    expect(loc.href).toBe('/index')
  })

  it('错误分支（HTTP 异常）同样处理', async () => {
    const loc = stubLocation('/index')
    const error = { message: 'Request failed with status code 500', config: { url: '/getInfo' }, response: { status: 500, data: { code: 500, msg: 'Not enough segments' } } }
    await expect(onRejected(error)).rejects.toThrow('Not enough segments')
    expect(mocks.removeToken).toHaveBeenCalledOnce()
    expect(mocks.message).toHaveBeenCalledOnce()
    expect(loc.href).toBe('/index')
  })

  it('登录页与退出接口只清除token，不提示不跳转', async () => {
    const loc = stubLocation('/login')
    await expect(onFulfilled(okResponse({ code: 500, msg: 'Signature verification failed' }))).rejects.toThrow()
    stubLocation('/system/user')
    await expect(onFulfilled(okResponse({ code: 500, msg: 'Signature verification failed' }, '/logout'))).rejects.toThrow()
    expect(mocks.removeToken).toHaveBeenCalledTimes(2)
    expect(mocks.message).not.toHaveBeenCalled()
    expect(loc.href).toBe('/login')
    expect(isRelogin.show).toBe(false)
  })

  it('其他错误信息走原有提示', async () => {
    stubLocation('/system/user')
    await expect(onFulfilled(okResponse({ code: 500, msg: '数据库连接失败' }))).rejects.toThrow('数据库连接失败')
    expect(mocks.removeToken).not.toHaveBeenCalled()
    expect(mocks.message).toHaveBeenCalledWith({ message: '数据库连接失败', type: 'error' })
  })
})
