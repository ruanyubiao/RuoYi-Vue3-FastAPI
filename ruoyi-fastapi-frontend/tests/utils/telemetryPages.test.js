import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/payload/config', () => ({
  getTelemetryConfig: vi.fn(async () => ({
    data: { page: [{ key: 'XL:FF', name: '总线' }, { name: '无key' }] }
  }))
}))

import { loadTelemetryPagesCached } from '@/utils/telemetryPages'
import { getTelemetryConfig } from '@/api/payload/config'

describe('utils/telemetryPages', () => {
  it('过滤无 key 的页并进程内复用', async () => {
    const a = await loadTelemetryPagesCached()
    const b = await loadTelemetryPagesCached()
    expect(a).toEqual([{ key: 'XL:FF', name: '总线' }])
    expect(b).toBe(a)
    expect(getTelemetryConfig).toHaveBeenCalledTimes(1)
  })
})
