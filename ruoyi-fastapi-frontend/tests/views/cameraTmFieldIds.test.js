/**
 * 相机页写死的遥测字段号必须与配置表一致。
 * 配置改号或改名后，这里应失败，避免页面继续读旧字段。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  D8_RES_FIELD_IDS,
  D8_STATS_FIELDS,
  D9_RES_FIELD_IDS,
  D9_STATS_FIELDS
} from '@/views/payload/board/camera/cameraTmFieldIds'

const CFG_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../ruoyi-fastapi-backend/assets/config'
)

/** 页面锁定的字段号。改号须同步配置与本表。 */
const PINNED_IDS = {
  d8Res: ['CAM036', 'CAM038'],
  d9Res: ['CAMF030', 'CAMF027'],
  d8Stats: ['CAM004', 'CAM005', 'CAM006', 'CAM007', 'CAM008', 'CAM010'],
  d9Stats: ['CAMF004', 'CAMF005', 'CAMF006', 'CAMF007', 'CAMF008', 'CAMF010']
}

/** id → 配置中的字段名。v1.6 / v1.7 开窗类名称不同，分开锁。 */
const EXPECT_NAMES = {
  v16: {
    CAM036: '开窗模式',
    CAM038: '缓存图像大小',
    CAMF030: '开窗模式',
    CAMF027: '缓存图像大小',
    CAM004: 'X坐标',
    CAM005: 'Y坐标',
    CAM006: '过阈值像元数',
    CAM007: '饱和像元数',
    CAM008: '平均灰度值',
    CAM010: '光斑能量',
    CAMF004: 'X坐标',
    CAMF005: 'Y坐标',
    CAMF006: '过阈值像元数',
    CAMF007: '饱和像元数',
    CAMF008: '平均灰度值',
    CAMF010: '光斑能量'
  },
  v17: {
    CAM036: '开窗大小',
    CAM038: '缓存图像尺寸',
    CAMF030: '开窗大小',
    CAMF027: '缓存图像尺寸',
    CAM004: 'X坐标',
    CAM005: 'Y坐标',
    CAM006: '过阈值像元数',
    CAM007: '饱和像元数',
    CAM008: '平均灰度值',
    CAM010: '光斑能量',
    CAMF004: 'X坐标',
    CAMF005: 'Y坐标',
    CAMF006: '过阈值像元数',
    CAMF007: '饱和像元数',
    CAMF008: '平均灰度值',
    CAMF010: '光斑能量'
  }
}

function loadCfg(fileName) {
  return JSON.parse(readFileSync(path.join(CFG_DIR, fileName), 'utf8'))
}

function fieldName(cfg, tableId, fieldId) {
  const row = cfg.table?.[tableId]?.row || []
  return row.find(item => item.id === fieldId)?.name
}

describe('camera page pinned telemetry field ids', () => {
  it('分辨率与统计字段号与页面常量一致', () => {
    expect(D8_RES_FIELD_IDS).toEqual(PINNED_IDS.d8Res)
    expect(D9_RES_FIELD_IDS).toEqual(PINNED_IDS.d9Res)
    expect(D9_RES_FIELD_IDS).not.toContain('CAMF029')
    expect(Object.values(D8_STATS_FIELDS)).toEqual(PINNED_IDS.d8Stats)
    expect(Object.values(D9_STATS_FIELDS)).toEqual(PINNED_IDS.d9Stats)
  })

  it.each([
    ['v16', 'XL-Camera-TeleMetryCfg.json', 'D8', 'D9'],
    ['v17', 'XL-Camera-V17-TeleMetryCfg.json', 'D8V17', 'D9V17']
  ])('%s 配置中写死字段的名称未改', (proto, fileName, d8Key, d9Key) => {
    const cfg = loadCfg(fileName)
    const expectNames = EXPECT_NAMES[proto]
    const d8Ids = [...PINNED_IDS.d8Res, ...PINNED_IDS.d8Stats]
    const d9Ids = [...PINNED_IDS.d9Res, ...PINNED_IDS.d9Stats]
    for (const id of d8Ids) {
      expect(fieldName(cfg, d8Key, id), `${fileName} ${d8Key}.${id}`).toBe(expectNames[id])
    }
    for (const id of d9Ids) {
      expect(fieldName(cfg, d9Key, id), `${fileName} ${d9Key}.${id}`).toBe(expectNames[id])
    }
  })
})
