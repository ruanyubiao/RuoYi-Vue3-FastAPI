/** el-scrollbar 贴底跟随：在底部才跟新内容，上翻阅读时钉住视口。 */

export const STICK_PIN_PX = 32

export function isNearBottom(wrap, pinPx = STICK_PIN_PX) {
  if (!wrap) return true
  const top = Number(wrap.scrollTop) || 0
  const height = Number(wrap.clientHeight) || 0
  const full = Number(wrap.scrollHeight) || 0
  return full - top - height <= pinPx
}

export function firstVisibleKeyed(wrap, root) {
  if (!wrap || !root) return null
  const r = wrap.getBoundingClientRect()
  const nodes = root.querySelectorAll('[data-stick-key]')
  for (const el of nodes) {
    const b = el.getBoundingClientRect()
    if (b.height <= 0) continue
    if (b.bottom > r.top + 1) {
      return { el, offset: b.top - r.top }
    }
  }
  return null
}

export function restoreAnchorOffset(wrap, el, offset) {
  if (!wrap || !el || el.isConnected === false) return
  const r = wrap.getBoundingClientRect()
  const b = el.getBoundingClientRect()
  wrap.scrollTop += b.top - r.top - Number(offset || 0)
}
