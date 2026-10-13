import { describe, expect, it } from 'vitest'
import { resolveTelecontrolFamily, sequenceListPath, telecontrolPages } from '@/utils/telecontrolFamily'

describe('utils/telecontrolFamily', () => {
  it('query.family 优先', () => {
    expect(resolveTelecontrolFamily({ path: '/biu/telecontrol/control', query: { family: 'xl' } })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/x', query: { family: 'biu' } })).toBe('biu')
  })

  it('路径段 /xl/ /biu/ /yj216/', () => {
    expect(resolveTelecontrolFamily({ path: '/xl/telecontrol/sequence', query: {} })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/biu/telecontrol/command', query: {} })).toBe('biu')
    expect(resolveTelecontrolFamily({ path: '/yj216/telecontrol/control', query: {} })).toBe('yj216')
  })

  it('兼容旧扁平 controlXl', () => {
    expect(resolveTelecontrolFamily({ path: '/payload/controlXl', query: {} })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/payload/control', query: {} })).toBe('biu')
  })

  it('没有 page 时用全部指令合成一页', () => {
    expect(telecontrolPages({ page: [{ id: 1, orderList: ['A'] }], order: { B: {} } })).toEqual([
      { id: 1, orderList: ['A'] }
    ])
    expect(telecontrolPages({ page: [], order: { YJ21611: { id: 'YJ21611' } } })).toEqual([
      { id: 'all', name: '遥控', orderList: ['YJ21611'] }
    ])
  })

  it('sequenceListPath', () => {
    expect(sequenceListPath('xl')).toBe('/xl/telecontrol/sequence')
    expect(sequenceListPath('biu')).toBe('/biu/telecontrol/sequence')
    expect(sequenceListPath('yj216')).toBe('/yj216/telecontrol/sequence')
    expect(sequenceListPath('other')).toBe('/biu/telecontrol/sequence')
  })
})
