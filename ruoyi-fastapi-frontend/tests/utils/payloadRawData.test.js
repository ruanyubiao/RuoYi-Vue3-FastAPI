import { describe, expect, it } from 'vitest'
import {
  HEX_INPUT_RULE_EXAMPLES,
  buildRawSendHex,
  bytesToHex,
  cleanHex,
  hexToBytes,
  isHexText,
  normalizeHexDisplay,
  parseEscapeToBytes,
  textToHex
} from '@/utils/payloadRawData'

describe('utils/payloadRawData', () => {
  describe('normalizeHexDisplay', () => {
    it.each(HEX_INPUT_RULE_EXAMPLES)('示例 %s → %s', (input, expected) => {
      expect(normalizeHexDisplay(input)).toBe(expected)
    })

    it('空输入返回空串', () => {
      expect(normalizeHexDisplay('')).toBe('')
      expect(normalizeHexDisplay('   ')).toBe('')
    })
  })

  describe('isHexText', () => {
    it('合法 HEX 通过', () => {
      expect(isHexText('AA BB 0C')).toBe(true)
    })

    it('含非法字符失败', () => {
      expect(isHexText('GG')).toBe(false)
    })

    it('input 模式仅校验字符集', () => {
      expect(isHexText('AAB', { input: true })).toBe(true)
    })
  })

  describe('hex roundtrip', () => {
    it('textToHex / hexToBytes', () => {
      const hex = textToHex('Hi')
      expect(hex).toBe('48 69')
      expect(Array.from(hexToBytes(hex))).toEqual([0x48, 0x69])
    })

    it('cleanHex 去掉非十六进制', () => {
      expect(cleanHex('a-b c')).toBe('abc')
    })
  })

  describe('parseEscapeToBytes', () => {
    it('\\x 与 \\n', () => {
      const bytes = parseEscapeToBytes('\\x0d\\n')
      expect(Array.from(bytes)).toEqual([0x0d, 0x0a])
    })
  })

  describe('buildRawSendHex', () => {
    it('HEX 模式成功', () => {
      const r = buildRawSendHex({ text: 'aa bb', isHex: true, parseEscape: false, lineEnding: 'none' })
      expect(r.ok).toBe(true)
      expect(r.hex).toBe('AA BB')
    })

    it('HEX 空数据失败', () => {
      const r = buildRawSendHex({ text: '   ', isHex: true, parseEscape: false, lineEnding: 'none' })
      expect(r.ok).toBe(false)
    })

    it('文本 + 转义', () => {
      const r = buildRawSendHex({ text: '\\x01', isHex: false, parseEscape: true, lineEnding: 'none' })
      expect(r.ok).toBe(true)
      expect(r.hex).toBe(bytesToHex([0x01]))
    })
  })
})
