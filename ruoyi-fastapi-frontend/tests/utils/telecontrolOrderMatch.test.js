import { describe, expect, it } from 'vitest'
import {
  hasOrderFilter,
  orderMatchesFilter,
  orderSearchText,
  TELECONTROL_ORDER_FILTER_PLACEHOLDER
} from '@/utils/telecontrolOrderMatch'

const sampleOrder = {
  id: 'K1501',
  name: '姿态控制',
  component: [{ title: '俯仰角' }, { title: '偏航角' }, { title: '  ' }, { title: null }]
}

const pointingOrder = {
  id: 'K2001',
  name: '指向设置',
  component: [{ title: '星敏模式' }]
}

const windowOrder = {
  id: 'K3001',
  name: '开窗参数',
  component: []
}

const photoOrder = {
  id: 'K3002',
  name: '拍照模式',
  component: [{ title: '曝光' }]
}

describe('utils/telecontrolOrderMatch', () => {
  it('TELECONTROL_ORDER_FILTER_PLACEHOLDER 已定义', () => {
    expect(TELECONTROL_ORDER_FILTER_PLACEHOLDER).toContain('空格')
    expect(TELECONTROL_ORDER_FILTER_PLACEHOLDER).toContain('|')
  })

  it('hasOrderFilter', () => {
    expect(hasOrderFilter('')).toBe(false)
    expect(hasOrderFilter('   ')).toBe(false)
    expect(hasOrderFilter(' K15 ')).toBe(true)
    expect(hasOrderFilter('|')).toBe(true)
  })

  it('orderSearchText 拼接 id/name/component，跳过空 title，不含 tip', () => {
    const text = orderSearchText(sampleOrder)
    expect(text).toContain('K1501')
    expect(text).toContain('姿态控制')
    expect(text).toContain('俯仰角')
    expect(text).toContain('偏航角')
    expect(orderSearchText({ ...sampleOrder, tip: '仅悬停' })).not.toContain('仅悬停')
    expect(orderSearchText({ id: 'A', name: 'B' })).toBe('A B')
  })

  it('空查询不过滤', () => {
    expect(orderMatchesFilter(sampleOrder, '')).toBe(true)
    expect(orderMatchesFilter(sampleOrder, '   ')).toBe(true)
  })

  it('多词 AND', () => {
    expect(orderMatchesFilter(sampleOrder, '姿态 俯仰')).toBe(true)
    expect(orderMatchesFilter(sampleOrder, '姿态 不存在')).toBe(false)
  })

  it('词内 OR：开窗|拍照', () => {
    expect(orderMatchesFilter(windowOrder, '开窗|拍照')).toBe(true)
    expect(orderMatchesFilter(photoOrder, '开窗 | 拍照')).toBe(true)
    expect(orderMatchesFilter(sampleOrder, '开窗|拍照')).toBe(false)
  })

  it('OR + 通配：开窗|拍*', () => {
    expect(orderMatchesFilter(windowOrder, '开窗|拍*')).toBe(true)
    expect(orderMatchesFilter(photoOrder, '开窗 | 拍*')).toBe(true)
    expect(orderMatchesFilter(sampleOrder, '开窗|拍*')).toBe(false)
  })

  it('空格优先于 |：指向|星敏 设置', () => {
    expect(orderMatchesFilter(pointingOrder, '指向|星敏 设置')).toBe(true)
    expect(orderMatchesFilter({ id: 'X', name: '星敏 设置', component: [] }, '指向|星敏 设置')).toBe(
      true
    )
    expect(orderMatchesFilter({ id: 'Y', name: '指向', component: [] }, '指向|星敏 设置')).toBe(
      false
    )
    expect(orderMatchesFilter({ id: 'Z', name: '设置', component: [] }, '指向|星敏 设置')).toBe(
      false
    )
  })

  it('引号短语：内部 | 不当 OR', () => {
    const order = { id: 'P', name: '指向|星敏 设置', component: [] }
    expect(orderMatchesFilter(order, '"指向|星敏 设置"')).toBe(true)
    expect(orderMatchesFilter(pointingOrder, '"指向|星敏 设置"')).toBe(false)
  })

  it('NOT', () => {
    expect(orderMatchesFilter(sampleOrder, '姿态 !偏航')).toBe(false)
    expect(orderMatchesFilter(sampleOrder, '姿态 !开窗')).toBe(true)
  })

  it('尾随 | 不误匹配全部（开窗|）', () => {
    expect(orderMatchesFilter(windowOrder, '开窗|')).toBe(true)
    expect(orderMatchesFilter({ id: 'Y', name: '其它', component: [] }, '开窗|')).toBe(false)
    expect(orderMatchesFilter(windowOrder, '|')).toBe(false)
  })

  it('中文？通配与 tip 不参与搜索', () => {
    expect(orderMatchesFilter({ id: 'K1501', name: 'x', component: [] }, 'K15？？')).toBe(true)
    const tipped = { ...sampleOrder, tip: '仅悬停显示不参与搜索' }
    expect(orderMatchesFilter(tipped, '仅悬停显示')).toBe(false)
  })
})
