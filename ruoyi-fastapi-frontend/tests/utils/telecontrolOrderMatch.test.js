import { describe, expect, it } from 'vitest'
import {
  getFilterKeywords,
  matchesAllKeywords,
  orderMatchesFilter,
  orderSearchText
} from '@/utils/telecontrolOrderMatch'

const sampleOrder = {
  id: 'TC001',
  name: '姿态控制',
  component: [{ title: '俯仰角' }, { title: '偏航角' }]
}

describe('utils/telecontrolOrderMatch', () => {
  it('getFilterKeywords 空格分词', () => {
    expect(getFilterKeywords('  姿态  TC ')).toEqual(['姿态', 'TC'])
  })

  it('matchesAllKeywords 全部命中', () => {
    expect(matchesAllKeywords('姿态控制 TC001', ['姿态', 'tc'])).toBe(true)
    expect(matchesAllKeywords('姿态控制', ['不存在'])).toBe(false)
  })

  it('orderSearchText 拼接 id/name/component', () => {
    expect(orderSearchText(sampleOrder)).toContain('TC001')
    expect(orderSearchText(sampleOrder)).toContain('俯仰角')
  })

  it('orderMatchesFilter 多词 AND', () => {
    expect(orderMatchesFilter(sampleOrder, '姿态 俯仰')).toBe(true)
    expect(orderMatchesFilter(sampleOrder, '姿态 不存在')).toBe(false)
    expect(orderMatchesFilter(sampleOrder, '')).toBe(true)
  })

  it('orderSearchText 不含 tip（筛选不受影响）', () => {
    const order = { ...sampleOrder, tip: '仅悬停显示不参与搜索' }
    const text = orderSearchText(order)
    expect(text).not.toContain('仅悬停显示')
    expect(orderMatchesFilter(order, '仅悬停显示')).toBe(false)
  })
})
