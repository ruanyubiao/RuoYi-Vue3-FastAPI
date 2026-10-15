/**
 * 遥控页关键展示组件：TelecontrolOrderTitle / TelecontrolCompLabel / HexInputTip
 * 用 @vue/test-utils 挂载，el-* 组件做轻量桩，只验证本组件自身逻辑。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TelecontrolOrderTitle from '@/components/Payload/TelecontrolOrderTitle.vue'
import TelecontrolCompLabel from '@/components/Payload/TelecontrolCompLabel.vue'
import HexInputTip from '@/components/Payload/HexInputTip.vue'
import { componentLabel } from '@/utils/telecontrolComponent'
import { HEX_INPUT_RULE_EXAMPLES, HEX_INPUT_RULE_LINES } from '@/utils/payloadRawData'

const stubs = {
  'el-tooltip': {
    props: ['content'],
    template: '<span class="stub-tooltip" :data-content="content"><slot /><slot name="content" /></span>'
  },
  'el-icon': { template: '<i class="stub-icon"><slot /></i>' },
  QuestionFilled: true,
  'question-filled': true
}

describe('TelecontrolOrderTitle', () => {
  it('默认显示 “id - name - N 字节”', () => {
    const w = mount(TelecontrolOrderTitle, {
      props: { order: { id: 'TC01', name: '复位' }, byteLen: 8 },
      global: { stubs }
    })
    expect(w.text()).toContain('TC01 - 复位 - 8 字节')
  })

  it('byteLen 为空时显示 “-”', () => {
    const w = mount(TelecontrolOrderTitle, {
      props: { order: { id: 'TC01', name: '复位' }, byteLen: '' },
      global: { stubs }
    })
    expect(w.text()).toContain('TC01 - 复位 - - 字节')
  })

  it('showBytes=false 只显示 id 与名称', () => {
    const w = mount(TelecontrolOrderTitle, {
      props: { order: { id: 'TC02', name: '加电' }, showBytes: false },
      global: { stubs }
    })
    expect(w.text().trim()).toBe('TC02 加电')
    expect(w.text()).not.toContain('字节')
  })

  it('order 为 null 不报错，也不显示提示图标', () => {
    const w = mount(TelecontrolOrderTitle, { props: { order: null }, global: { stubs } })
    expect(w.find('.stub-tooltip').exists()).toBe(false)
    expect(w.text()).toContain('字节')
  })
})

describe('TelecontrolCompLabel', () => {
  it('优先使用显式 label', () => {
    const w = mount(TelecontrolCompLabel, {
      props: { comp: { name: '原名' }, label: '覆盖名' },
      global: { stubs }
    })
    expect(w.find('.tc-comp-label-text').text()).toBe('覆盖名')
  })

  it('无 label 时回落到 componentLabel(comp, index)', () => {
    const comp = { name: '电压', type: 'edit' }
    const w = mount(TelecontrolCompLabel, { props: { comp, index: 3 }, global: { stubs } })
    expect(w.find('.tc-comp-label-text').text()).toBe(componentLabel(comp, 3))
  })
})

describe('HexInputTip', () => {
  it('渲染全部规则行与示例表', () => {
    const w = mount(HexInputTip, { global: { stubs } })
    expect(w.findAll('.hex-rule-list li')).toHaveLength(HEX_INPUT_RULE_LINES.length)
    expect(w.findAll('.hex-rule-table tbody tr')).toHaveLength(HEX_INPUT_RULE_EXAMPLES.length)
    expect(w.text()).toContain('Hex 文本规则')
  })
})
