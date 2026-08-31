import { describe, expect, it } from 'vitest'
import {
  ASSEMBLER_CAN_BIU,
  ASSEMBLER_PASSTHROUGH,
  CAN_ASSEMBLER_TO_PARSER,
  FALLBACK_ASSEMBLERS_CAN,
  PARSER_TM_CAN_BIU,
  PARSER_TM_CAN_XL,
  PARSER_TM_XL_BOARD,
  PARSER_TM_XL_CAMERA
} from '@/utils/pipelineIds'

describe('utils/pipelineIds', () => {
  it('CAN 组装器默认映射解析器', () => {
    expect(CAN_ASSEMBLER_TO_PARSER[ASSEMBLER_CAN_BIU]).toBe(PARSER_TM_CAN_BIU)
  })

  it('解析器 ID 与常量名一致（去掉 PARSER_ 后小写）', () => {
    expect(PARSER_TM_CAN_BIU).toBe('tm_can_biu')
    expect(PARSER_TM_CAN_XL).toBe('tm_can_xl')
    expect(PARSER_TM_XL_CAMERA).toBe('tm_xl_camera')
    expect(PARSER_TM_XL_BOARD).toBe('tm_xl_board')
  })

  it('fallback 列表含透传', () => {
    expect(FALLBACK_ASSEMBLERS_CAN.some(a => a.id === ASSEMBLER_PASSTHROUGH)).toBe(true)
  })
})
