import { describe, expect, it } from 'vitest'
import { isNearBottom, restoreAnchorOffset, STICK_PIN_PX } from '@/utils/stickScrollbar'

describe('stickScrollbar', () => {
  it('贴底判定：距底部不超过阈值即视为钉住', () => {
    expect(isNearBottom(null)).toBe(true)
    const wrap = { scrollTop: 100, clientHeight: 200, scrollHeight: 332 }
    expect(isNearBottom(wrap, STICK_PIN_PX)).toBe(true)
    expect(isNearBottom({ scrollTop: 0, clientHeight: 200, scrollHeight: 800 }, 32)).toBe(false)
  })

  it('restoreAnchorOffset 按元素位移回补 scrollTop', () => {
    const wrap = {
      scrollTop: 400,
      getBoundingClientRect: () => ({ top: 100 })
    }
    const el = {
      isConnected: true,
      getBoundingClientRect: () => ({ top: 180 })
    }
    restoreAnchorOffset(wrap, el, 20)
    expect(wrap.scrollTop).toBe(460)
  })

  it('restoreAnchorOffset 忽略已卸下的节点', () => {
    const wrap = { scrollTop: 10, getBoundingClientRect: () => ({ top: 0 }) }
    restoreAnchorOffset(wrap, { isConnected: false, getBoundingClientRect: () => ({ top: 50 }) }, 0)
    expect(wrap.scrollTop).toBe(10)
  })
})
