import { describe, expect, it } from 'vitest'
import {
  ASSEMBLER_CAN_BIU,
  ASSEMBLER_PASSTHROUGH,
  CAN_ASSEMBLER_TO_PARSER,
  FALLBACK_ASSEMBLERS_CAN,
  PARSER_TM_CAN_BIU
} from '@/utils/pipelineIds'

describe('utils/pipelineIds', () => {
  it('CAN 组装器默认映射解析器', () => {
    expect(CAN_ASSEMBLER_TO_PARSER[ASSEMBLER_CAN_BIU]).toBe(PARSER_TM_CAN_BIU)
  })

  it('fallback 列表含透传', () => {
    expect(FALLBACK_ASSEMBLERS_CAN.some(a => a.id === ASSEMBLER_PASSTHROUGH)).toBe(true)
  })
})
