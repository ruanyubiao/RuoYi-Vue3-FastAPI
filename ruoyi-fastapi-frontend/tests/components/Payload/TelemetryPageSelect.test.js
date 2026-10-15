/**
 * TelemetryPageSelect：遥测表下拉（分组、筛选、自动加载、自动选中第一项）。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/telemetryPages', () => ({
  loadTelemetryPagesCached: vi.fn()
}))

import { loadTelemetryPagesCached } from '@/utils/telemetryPages'
import TelemetryPageSelect from '@/components/Payload/TelemetryPageSelect.vue'

const PAGES = [
  { key: 'BIU:FF', id: 'FF', label: 'BIU FF 综合遥测', family: 'biu' },
  { key: 'XL:D8', id: 'D8', label: 'XL D8 相机遥测', family: 'xl' }
]

const stubs = {
  'el-select': {
    props: ['modelValue', 'filterMethod'],
    emits: ['update:modelValue', 'change', 'visible-change'],
    template: '<div class="stub-select"><slot /></div>'
  },
  'el-option-group': { props: ['label'], template: '<div class="stub-group" :data-label="label"><slot /></div>' },
  'el-option': { props: ['label', 'value'], template: '<div class="stub-option" :data-value="value">{{ label }}</div>' }
}

beforeEach(() => {
  loadTelemetryPagesCached.mockReset()
})

describe('TelemetryPageSelect', () => {
  it('使用父组件传入的 pages 渲染选项，不自己请求', () => {
    const w = mount(TelemetryPageSelect, { props: { pages: PAGES }, global: { stubs } })
    const values = w.findAll('.stub-option').map(o => o.attributes('data-value'))
    expect(values.sort()).toEqual(['BIU:FF', 'XL:D8'])
    expect(loadTelemetryPagesCached).not.toHaveBeenCalled()
  })

  it('筛选：filter-method 只保留匹配项', async () => {
    const w = mount(TelemetryPageSelect, { props: { pages: PAGES }, global: { stubs } })
    const select = w.findComponent(stubs['el-select'])
    select.props('filterMethod')('D8')
    await w.vm.$nextTick()
    const values = w.findAll('.stub-option').map(o => o.attributes('data-value'))
    expect(values).toEqual(['XL:D8'])
  })

  it('autoLoad + autoSelectFirst：加载后发出 loaded 与 update:modelValue', async () => {
    loadTelemetryPagesCached.mockResolvedValue(PAGES)
    const w = mount(TelemetryPageSelect, {
      props: { autoLoad: true, autoSelectFirst: true },
      global: { stubs }
    })
    await flushPromises()
    expect(loadTelemetryPagesCached).toHaveBeenCalledTimes(1)
    expect(w.emitted('loaded')[0][0]).toEqual(PAGES)
    expect(w.emitted('update:modelValue')[0]).toEqual(['BIU:FF'])
  })

  it('已有选中值时 autoSelectFirst 不覆盖', async () => {
    loadTelemetryPagesCached.mockResolvedValue(PAGES)
    const w = mount(TelemetryPageSelect, {
      props: { autoLoad: true, autoSelectFirst: true, modelValue: 'XL:D8' },
      global: { stubs }
    })
    await flushPromises()
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })

  it('选择变化透传 change 事件', async () => {
    const w = mount(TelemetryPageSelect, { props: { pages: PAGES }, global: { stubs } })
    const select = w.findComponent(stubs['el-select'])
    select.vm.$emit('update:modelValue', 'XL:D8')
    select.vm.$emit('change', 'XL:D8')
    expect(w.emitted('update:modelValue')[0]).toEqual(['XL:D8'])
    expect(w.emitted('change')[0]).toEqual(['XL:D8'])
  })
})
