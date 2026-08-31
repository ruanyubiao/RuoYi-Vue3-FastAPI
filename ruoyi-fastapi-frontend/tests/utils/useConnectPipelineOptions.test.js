import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/payload/device', () => ({
  listParsers: vi.fn(),
  listAssemblers: vi.fn()
}))

import {
  confirmOpenLabel,
  isAlreadyOpen,
  loadAssemblerOptions,
  loadParserOptions,
  mapPipelineOptions,
  reuseSuccessMessage
} from '@/utils/useConnectPipelineOptions'
import { listAssemblers, listParsers } from '@/api/payload/device'

describe('utils/useConnectPipelineOptions', () => {
  it('mapPipelineOptions 归一化多种形态', () => {
    expect(mapPipelineOptions(null)).toEqual([])
    expect(
      mapPipelineOptions([
        'passthrough',
        { id: 'p1', name: 'P1' },
        { parserId: 'p2', label: 'P2' },
        { assemblerId: 'a1' },
        {}
      ])
    ).toEqual([
      { id: 'passthrough', name: 'passthrough' },
      { id: 'p1', name: 'P1' },
      { id: 'p2', name: 'P2' },
      { id: 'a1', name: 'a1' }
    ])
  })

  it('confirmOpenLabel / isAlreadyOpen / reuseSuccessMessage', () => {
    expect(confirmOpenLabel(true)).toBe('使用')
    expect(confirmOpenLabel(false)).toBe('打开')
    expect(isAlreadyOpen({ data: { status: 'already_open' } })).toBe(true)
    expect(isAlreadyOpen({ data: { status: 'opened' } })).toBe(false)
    expect(reuseSuccessMessage('can')).toContain('can')
    expect(reuseSuccessMessage('serial')).toContain('串口')
    expect(reuseSuccessMessage('udp')).toContain('UDP')
  })

  it('loadParserOptions 成功映射 API', async () => {
    listParsers.mockResolvedValueOnce({ data: { parsers: [{ id: 'tm_can_biu', name: 'BIU' }] } })
    await expect(loadParserOptions([{ id: 'fb', name: 'FB' }])).resolves.toEqual([
      { id: 'tm_can_biu', name: 'BIU' }
    ])
  })

  it('loadParserOptions 失败返回 fallback 副本', async () => {
    const fb = [{ id: 'fb', name: 'FB' }]
    listParsers.mockRejectedValueOnce(new Error('net'))
    const got = await loadParserOptions(fb)
    expect(got).toEqual(fb)
    expect(got).not.toBe(fb)
  })

  it('loadAssemblerOptions 传递 srcKind', async () => {
    listAssemblers.mockResolvedValueOnce({ data: [{ id: 'can_biu', name: 'CAN' }] })
    await loadAssemblerOptions('can', [])
    expect(listAssemblers).toHaveBeenCalledWith('can')
  })
})
