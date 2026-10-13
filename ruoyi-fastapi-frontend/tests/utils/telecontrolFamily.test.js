import { describe, expect, it } from 'vitest'
import { resolveTelecontrolFamily, sequenceListPath } from '@/utils/telecontrolFamily'

describe('utils/telecontrolFamily', () => {
  it('query.family 优先', () => {
    expect(resolveTelecontrolFamily({ path: '/biu/telecontrol/control', query: { family: 'xl' } })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/x', query: { family: 'biu' } })).toBe('biu')
  })

  it('路径段 /xl/ /biu/', () => {
    expect(resolveTelecontrolFamily({ path: '/xl/telecontrol/sequence', query: {} })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/biu/telecontrol/command', query: {} })).toBe('biu')
  })

  it('兼容旧扁平 controlXl', () => {
    expect(resolveTelecontrolFamily({ path: '/payload/controlXl', query: {} })).toBe('xl')
    expect(resolveTelecontrolFamily({ path: '/payload/control', query: {} })).toBe('biu')
  })

  it('sequenceListPath', () => {
    expect(sequenceListPath('xl')).toBe('/xl/telecontrol/sequence')
    expect(sequenceListPath('biu')).toBe('/biu/telecontrol/sequence')
    expect(sequenceListPath('other')).toBe('/biu/telecontrol/sequence')
  })
})
