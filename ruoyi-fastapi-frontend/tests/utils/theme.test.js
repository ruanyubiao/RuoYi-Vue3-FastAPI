import { describe, expect, it } from 'vitest'
import { getDarkColor, getLightColor, hexToRgb, rgbToHex } from '@/utils/theme'

describe('utils/theme', () => {
  it('hexToRgb / rgbToHex 往返', () => {
    expect(hexToRgb('#409EFF')).toEqual([64, 158, 255])
    expect(rgbToHex(64, 158, 255)).toBe('#409eff')
    expect(rgbToHex(15, 1, 2)).toBe('#0f0102')
  })

  it('getLightColor level 0 不变', () => {
    expect(getLightColor('#000000', 0)).toBe('#000000')
  })

  it('getDarkColor level 1 趋近黑', () => {
    expect(getDarkColor('#ffffff', 1)).toBe('#000000')
  })
})
