/**
 * LVDS 工程曲线页生命周期：定时器 / resize 监听不泄漏，卸载后在途请求不再操作已销毁图表。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'

const chartApi = { setOption: vi.fn(), on: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
vi.mock('echarts', () => ({ init: vi.fn(() => chartApi) }))
vi.mock('@/api/payload/lvds', () => ({
  listLvdsSignals: vi.fn(),
  getLvdsData: vi.fn()
}))

import { getLvdsData, listLvdsSignals } from '@/api/payload/lvds'
import Engineering from '@/views/payload/lvds/engineering/index.vue'

const passthrough = { template: '<div><slot /></div>' }
const stubs = new Proxy({}, { get: (_t, k) => (String(k).startsWith('el-') ? passthrough : undefined), has: (_t, k) => String(k).startsWith('el-') })

let intervals
beforeEach(() => {
  vi.clearAllMocks()
  intervals = new Set()
  const realSet = globalThis.setInterval
  const realClear = globalThis.clearInterval
  vi.spyOn(globalThis, 'setInterval').mockImplementation((fn, ms) => {
    const id = realSet(() => {}, 100000)
    intervals.add(id)
    return id
  })
  vi.spyOn(globalThis, 'clearInterval').mockImplementation(id => {
    intervals.delete(id)
    realClear(id)
  })
  listLvdsSignals.mockResolvedValue({ data: [{ id: 'S1' }, { id: 'S2' }] })
  getLvdsData.mockResolvedValue({ data: { points: [{ t: 1, v: 2 }] } })
})
afterEach(() => {
  for (const id of intervals) clearInterval(id)
  vi.restoreAllMocks()
})

describe('LVDS 工程页生命周期', () => {
  it('KeepAlive 首次挂载只保留一个轮询定时器，卸载后全部清除', async () => {
    const show = ref(true)
    const Host = defineComponent({
      setup: () => () => h(KeepAlive, null, show.value ? [h(Engineering)] : [])
    })
    const w = mount(Host, { global: { stubs }, attachTo: document.body })
    await flushPromises()
    expect(intervals.size).toBe(1)
    w.unmount()
    expect(intervals.size).toBe(0)
  })

  it('卸载时移除 resize 监听', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')
    const w = mount(Engineering, { global: { stubs } })
    await flushPromises()
    const handler = add.mock.calls.find(c => c[0] === 'resize')?.[1]
    expect(handler).toBeTypeOf('function')
    w.unmount()
    expect(remove).toHaveBeenCalledWith('resize', handler)
  })

  it('卸载后在途请求返回不再调用已销毁图表', async () => {
    const pending = []
    getLvdsData.mockImplementation(() => new Promise(r => { pending.push(r) }))
    const w = mount(Engineering, { global: { stubs } })
    await flushPromises()
    const calls = chartApi.setOption.mock.calls.length
    w.unmount()
    for (let i = 0; i < 5 && pending.length; i++) {
      pending.shift()({ data: { points: [] } })
      await flushPromises()
    }
    await nextTick()
    expect(chartApi.setOption.mock.calls.length).toBe(calls)
  })
})
