import { describe, expect, it } from 'vitest'
import {
  cameraTmCfgScope,
  clearAllTelemetryCfg,
  clearTelemetryCfg,
  isTelemetryCfgStale,
  saveTelemetryCfg,
  takeTelemetryCfg,
  tmTypeCfgScope,
  xlBoardTmCfgScope
} from '@/utils/telemetryCfgCache'

describe('utils/telemetryCfgCache', () => {
  const scope = tmTypeCfgScope('D8')
  const rows = [{ id: '1', name: 'f1' }]

  it('scope 辅助函数', () => {
    expect(tmTypeCfgScope('d8')).toBe('tm:D8')
    expect(cameraTmCfgScope('d9')).toBe('camera:D9')
    expect(xlBoardTmCfgScope('rkdj')).toBe('xl:rkdj')
  })

  it('save / take 往返', () => {
    saveTelemetryCfg(scope, {
      name: '表1',
      tableKey: 'D8',
      cfgRows: rows,
      cfgDatetime: '2026-01-01',
      cfgMtime: '100'
    })
    const cached = takeTelemetryCfg(scope, { cfgDatetime: '2026-01-01', cfgMtime: '100' })
    expect(cached?.cfgRows).toEqual(rows)
    expect(cached?.name).toBe('表1')
  })

  it('cfgMtime 变化视为过期', () => {
    saveTelemetryCfg(scope, { cfgRows: rows, cfgMtime: '1' })
    expect(takeTelemetryCfg(scope, { cfgMtime: '2' })).toBeNull()
  })

  it('isTelemetryCfgStale', () => {
    saveTelemetryCfg(scope, { cfgRows: rows, cfgMtime: '1' })
    expect(isTelemetryCfgStale(scope, { cfgMtime: '2' })).toBe(true)
    expect(isTelemetryCfgStale(scope, { cfgMtime: '1' })).toBe(false)
  })

  it('clearTelemetryCfg / clearAllTelemetryCfg', () => {
    saveTelemetryCfg(scope, { cfgRows: rows })
    saveTelemetryCfg(tmTypeCfgScope('FF'), { cfgRows: rows })
    clearTelemetryCfg(scope)
    expect(takeTelemetryCfg(scope)).toBeNull()
    clearAllTelemetryCfg()
    expect(takeTelemetryCfg(tmTypeCfgScope('FF'))).toBeNull()
  })
})
