/**
 * src/api/payload/*.js 契约测试
 *
 * 1. 每个导出的请求函数都能被调用，并交给 @/utils/request 一个合法的 { url, method }；
 * 2. url 以 /payload/ 开头、method 为 get/post/put/delete；
 * 3. 前后端路由对拍：把前端 url 中的动态段换成 {param} 后，必须能在
 *    ruoyi-fastapi-backend/module_payload/controller/*.py 里找到同方法同路径的路由。
 *    后端改名/删接口而前端没跟上时，这个用例会直接失败。
 */
import fs from 'node:fs'
import path from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue', () => ({ h: vi.fn() }))
vi.mock('element-plus', () => ({ ElButton: {}, ElMessageBox: { confirm: vi.fn() } }))
vi.mock('@/utils/request', () => ({
  default: vi.fn((cfg) => Promise.resolve({ code: 200, data: null, __cfg: cfg }))
}))

import request from '@/utils/request'
import * as board from '@/api/payload/board'
import * as camera from '@/api/payload/camera'
import * as config from '@/api/payload/config'
import * as configFile from '@/api/payload/configFile'
import * as device from '@/api/payload/device'
import * as lvds from '@/api/payload/lvds'
import * as sequence from '@/api/payload/sequence'
import * as telecontrol from '@/api/payload/telecontrol'
import * as telemetry from '@/api/payload/telemetry'
import * as tmCalc from '@/api/payload/tmCalc'

const MODULES = { board, camera, config, configFile, device, lvds, sequence, telecontrol, telemetry, tmCalc }

/** 非请求函数（纯逻辑 / UI 辅助），不参与契约检查 */
const NON_REQUEST = new Set(['decideFileParseAction', 'askCompletedFileParse', 'startFileParsePoll'])

const SAMPLE_ARGS = ['xl', 'rkdj', { id: 1 }, { a: 1 }]

const BACKEND_CONTROLLER_DIR = path.resolve(
  __dirname,
  '../../../ruoyi-fastapi-backend/module_payload/controller'
)

function loadBackendRoutes() {
  const routes = new Set()
  for (const file of fs.readdirSync(BACKEND_CONTROLLER_DIR)) {
    if (!file.endsWith('.py')) continue
    const src = fs.readFileSync(path.join(BACKEND_CONTROLLER_DIR, file), 'utf-8')
    const prefix = /prefix=\s*'([^']+)'/.exec(src)?.[1]
    if (!prefix) continue
    const re = /@\w+\.(get|post|put|delete|patch)\(\s*'([^']*)'/g
    let m
    while ((m = re.exec(src))) {
      routes.add(`${m[1].toUpperCase()} ${normalize(prefix + m[2])}`)
    }
  }
  return routes
}

/** /payload/board/xl/rkdj/x 与 /payload/board/{family}/{board}/x 统一成 {} 占位 */
function normalize(url) {
  return url
    .split('?')[0]
    .replace(/\{[^}]+\}/g, '{}')
    .replace(/\/$/, '')
}

function collectCalls() {
  const calls = []
  for (const [modName, mod] of Object.entries(MODULES)) {
    for (const [fnName, fn] of Object.entries(mod)) {
      if (typeof fn !== 'function' || NON_REQUEST.has(fnName)) continue
      request.mockClear()
      try {
        fn(...SAMPLE_ARGS)
      } catch {
        // 个别函数对参数有前置校验，忽略同步异常，只看是否发出请求
      }
      for (const [cfg] of request.mock.calls) {
        calls.push({ modName, fnName, cfg })
      }
    }
  }
  return calls
}

describe('payload API 请求函数', () => {
  beforeEach(() => request.mockClear())

  it('每个模块都有导出的请求函数', () => {
    for (const [name, mod] of Object.entries(MODULES)) {
      const fns = Object.entries(mod).filter(([k, v]) => typeof v === 'function' && !NON_REQUEST.has(k))
      expect(fns.length, name).toBeGreaterThan(0)
    }
  })

  it('请求配置合法：url 以 /payload/ 开头、method 合法', () => {
    const calls = collectCalls()
    expect(calls.length).toBeGreaterThan(60)
    for (const { modName, fnName, cfg } of calls) {
      const where = `${modName}.${fnName}`
      expect(typeof cfg.url, where).toBe('string')
      expect(cfg.url.startsWith('/payload/'), `${where} → ${cfg.url}`).toBe(true)
      expect(['get', 'post', 'put', 'delete'], where).toContain(String(cfg.method || 'get').toLowerCase())
      if (String(cfg.method).toLowerCase() === 'get') {
        expect(cfg.data, `${where} GET 不应带 body`).toBeUndefined()
      }
    }
  })

  it('getDeviceStatus 把 deviceId 放到 query', () => {
    device.getDeviceStatus('can:0:0:1')
    expect(request).toHaveBeenCalledWith({
      url: '/payload/device/status',
      method: 'get',
      params: { deviceId: 'can:0:0:1' }
    })
  })

  it('listAssemblers：srcKind 为空时不带 params', () => {
    device.listAssemblers()
    expect(request.mock.calls[0][0].params).toBeUndefined()
    device.listAssemblers('can')
    expect(request.mock.calls[1][0].params).toEqual({ srcKind: 'can' })
  })
})

describe('前后端路由对拍', () => {
  const backend = loadBackendRoutes()

  it('能从后端控制器解析出路由', () => {
    expect(backend.size).toBeGreaterThan(80)
    expect(backend.has('GET /payload/telemetry/config')).toBe(true)
    expect(backend.has('GET /payload/telemetry/def')).toBe(true)
  })

  it('前端调用的每个接口在后端都存在（方法 + 路径）', () => {
    const missing = []
    for (const { modName, fnName, cfg } of collectCalls()) {
      const method = String(cfg.method || 'get').toUpperCase()
      const url = normalize(cfg.url)
      // 前端用模板字符串拼动态段（如 /payload/board/xl/rkdj/...），逐段尝试替换为 {}
      const segs = url.split('/')
      let ok = backend.has(`${method} ${url}`)
      for (let mask = 1; !ok && mask < 1 << segs.length; mask++) {
        const cand = segs.map((s, i) => (mask & (1 << i) && i > 2 ? '{}' : s)).join('/')
        ok = backend.has(`${method} ${cand}`)
      }
      if (!ok) missing.push(`${modName}.${fnName}: ${method} ${cfg.url}`)
    }
    expect(missing).toEqual([])
  })
})
