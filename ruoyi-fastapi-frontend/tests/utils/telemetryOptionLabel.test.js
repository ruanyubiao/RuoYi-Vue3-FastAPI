import { describe, expect, it } from 'vitest'
import { groupTelemetryPages, telemetryOptionLabel, telemetryOptionMatch } from '@/utils/telemetryOptionLabel'

const pages = [
  { key: 'XL:FF', id: 'XL:FF', localKey: 'FF', name: '总线', family: 'xl' },
  { key: 'BIU:01', id: 'BIU:01', localKey: '01', name: '姿态', family: 'biu' },
  { key: 'CAM:D8', id: 'CAM:D8', localKey: 'D8', name: '相机慢遥测', family: 'xl' }
]

describe('utils/telemetryOptionLabel', () => {
  it('telemetryOptionLabel 带 family 前缀', () => {
    expect(telemetryOptionLabel(pages[0])).toBe('XL-FF：总线')
    expect(telemetryOptionLabel({ id: 'X', name: '' })).toBe('X')
  })

  it('telemetryOptionMatch 模糊分词', () => {
    expect(telemetryOptionMatch('', pages[0])).toBe(true)
    expect(telemetryOptionMatch('xl ff', pages[0])).toBe(true)
    expect(telemetryOptionMatch('相机', pages[2])).toBe(true)
    expect(telemetryOptionMatch('不存在', pages[0])).toBe(false)
  })

  it('groupTelemetryPages 分组与 keepKey', () => {
    const groups = groupTelemetryPages(pages, 'xl', 'BIU:01')
    const labels = groups.map(g => g.label)
    expect(labels).toContain('XL')
    expect(labels).toContain('BIU')
    const biuGroup = groups.find(g => g.label === 'BIU')
    expect(biuGroup?.options.some(p => p.key === 'BIU:01')).toBe(true)
  })
})
