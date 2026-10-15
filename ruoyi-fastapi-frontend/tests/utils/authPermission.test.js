/**
 * 登录态与按钮级权限：utils/auth.js、utils/permission.js、utils/errorCode.js
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const store = { permissions: [], roles: [] }
vi.mock('@/store/modules/user', () => ({ default: () => store }))

import Cookies from 'js-cookie'
import { getToken, removeToken, setToken } from '@/utils/auth'
import { checkPermi, checkRole } from '@/utils/permission'
import errorCode from '@/utils/errorCode'

describe('auth token cookie', () => {
  afterEach(() => removeToken())

  it('set / get / remove 使用 Admin-Token', () => {
    expect(getToken()).toBeUndefined()
    setToken('abc')
    expect(getToken()).toBe('abc')
    expect(Cookies.get('Admin-Token')).toBe('abc')
    removeToken()
    expect(getToken()).toBeUndefined()
  })
})

describe('checkPermi', () => {
  let err
  beforeEach(() => {
    store.permissions = []
    err = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => err.mockRestore())

  it('*:*:* 拥有全部权限', () => {
    store.permissions = ['*:*:*']
    expect(checkPermi(['payload:device:open'])).toBe(true)
  })

  it('命中任一权限即通过，否则拒绝', () => {
    store.permissions = ['payload:telecontrol:view']
    expect(checkPermi(['payload:telecontrol:send', 'payload:telecontrol:view'])).toBe(true)
    expect(checkPermi(['payload:telecontrol:send'])).toBe(false)
  })

  it('空数组 / 非数组参数返回 false 并打印用法提示', () => {
    expect(checkPermi([])).toBe(false)
    expect(checkPermi('payload:x')).toBe(false)
    expect(err).toHaveBeenCalledTimes(2)
  })
})

describe('checkRole', () => {
  let err
  beforeEach(() => {
    store.roles = []
    err = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => err.mockRestore())

  it('admin 拥有全部角色', () => {
    store.roles = ['admin']
    expect(checkRole(['editor'])).toBe(true)
  })

  it('普通角色按包含判断', () => {
    store.roles = ['common']
    expect(checkRole(['common'])).toBe(true)
    expect(checkRole(['editor'])).toBe(false)
    expect(checkRole(null)).toBe(false)
  })
})

describe('errorCode', () => {
  it('包含 401/403/404 与 default 文案', () => {
    for (const k of ['401', '403', '404', 'default']) {
      expect(typeof errorCode[k]).toBe('string')
      expect(errorCode[k].length).toBeGreaterThan(0)
    }
  })
})
