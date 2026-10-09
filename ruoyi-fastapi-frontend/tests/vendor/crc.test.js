import { describe, expect, it } from 'vitest'
import { CRC_ALGORITHMS, checksumAlgoTree, computeCrc, computeSum, crcAlgoTree, formatCrcValue, sum8 } from '@/vendor/crc'

const CHECK_BYTES = new TextEncoder().encode('123456789')

describe('vendor/crc', () => {
  it('12 个算法对 123456789 的 Check 值一致', () => {
    expect(CRC_ALGORITHMS).toHaveLength(12)
    for (const algo of CRC_ALGORITHMS) {
      expect(computeCrc(algo.id, CHECK_BYTES), algo.name).toBe(algo.check)
    }
  })

  it('formatCrcValue 无前缀、补零、BIN 每 8 位一组', () => {
    expect(formatCrcValue(0x4b, 8)).toEqual({
      hex: '4B',
      dec: '75',
      oct: '113',
      bin: '01001011'
    })
    expect(formatCrcValue(0x4b37, 16)).toEqual({
      hex: '4B37',
      dec: '19255',
      oct: '45467',
      bin: '01001011 00110111'
    })
    const f32 = formatCrcValue(0xcbf43926, 32)
    expect(f32.hex).toBe('CBF43926')
    expect(f32.bin).toBe('11001011 11110100 00111001 00100110')
    expect(f32.dec).toBe(String(0xcbf43926 >>> 0))
  })

  it('SUM8 是字节累加取低 8 位', () => {
    expect(sum8(new Uint8Array([0x22]))).toBe(0x22)
    expect(sum8(new Uint8Array([0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0x00]))).toBe(0xec)
    expect(sum8(new Uint8Array([0xff, 0x02]))).toBe(0x01)
  })

  it('SUM16/32 取对应低位，补码再加为 0，NOT 为按位取反', () => {
    const bytes = new Uint8Array([0xff, 0x02])
    expect(computeSum('sum16', bytes)).toBe(0x0101)
    expect(computeSum('sum32', bytes)).toBe(0x0101)
    expect(computeSum('sum8-cpl', bytes)).toBe(0xff)
    expect((computeSum('sum8', bytes) + computeSum('sum8-cpl', bytes)) & 0xff).toBe(0)
    expect(computeSum('sum8-not', bytes)).toBe(0xfe)
    expect(computeSum('sum16-not', bytes)).toBe(0xfefe)
  })

  it('校验树第一组是 SUM', () => {
    expect(checksumAlgoTree()[0].id).toBe('SUM')
    expect(checksumAlgoTree()[0].children.map(n => n.id)).toContain('sum8')
  })

  it('树按位宽三组', () => {
    const tree = crcAlgoTree()
    expect(tree.map(n => n.id)).toEqual(['CRC-8', 'CRC-16', 'CRC-32'])
    expect(tree.every(n => n.children.length === 4)).toBe(true)
  })
})
