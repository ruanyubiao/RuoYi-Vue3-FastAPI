import { describe, expect, it, vi } from 'vitest'

vi.mock('vue', () => ({
  h: vi.fn()
}))
vi.mock('element-plus', () => ({
  ElButton: {},
  ElMessageBox: {}
}))
vi.mock('@/utils/request', () => ({
  default: vi.fn()
}))

import { decideFileParseAction } from '@/api/payload/telemetry'

describe('decideFileParseAction', () => {
  it('有缓存直接用，不弹确认框', () => {
    expect(
      decideFileParseAction(
        {
          complete: true,
          frameCountExact: true,
          parsedDone: true,
          hasData: true,
          frameCount: 12,
          type: 'BIU:FF',
          workerAlive: false,
          sessionGone: false
        },
        'BIU:FF'
      )
    ).toBe('use')
  })

  it('扫描中但已有数据应跟进度，不能当完成复用', () => {
    expect(
      decideFileParseAction(
        {
          complete: false,
          frameCountExact: false,
          hasData: true,
          frameCount: 1,
          status: 'ready',
          type: 'BIU:FF',
          workerAlive: true,
          sessionGone: false
        },
        'BIU:FF'
      )
    ).toBe('follow')
  })

  it('worker 还在拆、尚无帧，第二窗也跟进度', () => {
    expect(
      decideFileParseAction(
        {
          complete: false,
          frameCountExact: false,
          hasData: false,
          frameCount: 0,
          status: 'parsing',
          type: 'BIU:FF',
          workerAlive: true,
          alreadyParsing: true
        },
        'BIU:FF'
      )
    ).toBe('follow')
  })

  it('sessionGone 且无数据才当新解析', () => {
    expect(
      decideFileParseAction({ sessionGone: true, workerAlive: false, hasData: false }, 'BIU:FF')
    ).toBe('parse')
  })

  it('失败的 0 帧精确扫描不能当成现有解析', () => {
    expect(
      decideFileParseAction(
        {
          status: 'error',
          error: '未找到匹配遥测类型的完整帧',
          complete: true,
          frameCountExact: true,
          hasData: false,
          frameCount: 0,
          type: 'CPAZX',
          workerAlive: true
        },
        'CPAZX'
      )
    ).toBe('parse')
  })

  it('扫描中断、worker 已死、只剩部分帧则冻住现有', () => {
    expect(
      decideFileParseAction(
        {
          complete: false,
          frameCountExact: false,
          hasData: true,
          frameCount: 8,
          status: 'ready',
          type: 'BIU:FF',
          workerAlive: false
        },
        'BIU:FF'
      )
    ).toBe('use')
  })
})
