import { describe, expect, it } from 'vitest'
import { fileFrameDataTs, formatTelemetryTs, parseRecvFileStartMs } from '@/utils/recvFileTime'

describe('utils/recvFileTime', () => {
  it('parseRecvFileStartMs 从路径解析时间戳', () => {
    const ms = parseRecvFileStartMs('E:/data/recv_20260824_103104_356.bin')
    expect(ms).not.toBeNull()
    expect(formatTelemetryTs(ms)).toBe('2026-08-24 10:31:04.356')
  })

  it('parseRecvFileStartMs 无匹配返回 null', () => {
    expect(parseRecvFileStartMs('no_stamp.bin')).toBeNull()
  })

  it('fileFrameDataTs 第 n 帧递增 1 秒', () => {
    const path = 'foo_20260101_000000_000.dat'
    expect(fileFrameDataTs(path, 1)).toBe('2026-01-01 00:00:00.000')
    expect(fileFrameDataTs(path, 3)).toBe('2026-01-01 00:00:02.000')
  })

  it('formatTelemetryTs 非法返回空', () => {
    expect(formatTelemetryTs(NaN)).toBe('')
  })
})
