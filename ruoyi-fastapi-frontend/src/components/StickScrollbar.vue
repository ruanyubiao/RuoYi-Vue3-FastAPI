<template>
  <el-scrollbar ref="barRef" class="stick-scrollbar" @scroll="onScroll">
    <div ref="contentRef" class="stick-scrollbar__content">
      <slot />
    </div>
  </el-scrollbar>
</template>

<script setup name="StickScrollbar">
/**
 * 贴底跟随滚动条（包一层 el-scrollbar）。
 * 停在底部：新内容自动滚到最新；上翻阅读：滚动条不拽走。
 * 列表行加 data-stick-key（稳定 id），满窗从头部裁掉时仍钉在正在看的那一行。
 * 清空 / 切源后调用 pinToBottom()，下一批回到最新。
 */
import {
  STICK_PIN_PX,
  firstVisibleKeyed,
  isNearBottom,
  restoreAnchorOffset
} from '@/utils/stickScrollbar'

const props = defineProps({
  pinPx: { type: Number, default: STICK_PIN_PX }
})

const barRef = ref(null)
const contentRef = ref(null)
const stickToBottom = ref(true)

let lastAnchor = null
let applying = false
let scheduled = false
let mo = null
let ro = null

function wrapEl() {
  return barRef.value?.wrapRef || null
}

function threshold() {
  const n = Number(props.pinPx)
  return Number.isFinite(n) && n >= 0 ? n : STICK_PIN_PX
}

function rememberAnchor() {
  const hit = firstVisibleKeyed(wrapEl(), contentRef.value)
  if (!hit?.el) {
    lastAnchor = null
    return
  }
  lastAnchor = {
    key: hit.el.getAttribute('data-stick-key'),
    offset: hit.offset
  }
}

function restoreLastAnchor() {
  if (!lastAnchor?.key) return
  const root = contentRef.value
  const wrap = wrapEl()
  if (!root || !wrap) return
  const el = root.querySelector(`[data-stick-key="${lastAnchor.key}"]`)
  if (!el) return
  restoreAnchorOffset(wrap, el, lastAnchor.offset)
}

function pinNow() {
  const wrap = wrapEl()
  if (wrap) wrap.scrollTop = wrap.scrollHeight
  stickToBottom.value = true
  lastAnchor = null
}

function pinToBottom() {
  stickToBottom.value = true
  lastAnchor = null
  nextTick(() => {
    applying = true
    try {
      pinNow()
    } finally {
      applying = false
    }
  })
}

function onScroll() {
  if (applying) return
  const wrap = wrapEl()
  const pinned = isNearBottom(wrap, threshold())
  stickToBottom.value = pinned
  if (!pinned) rememberAnchor()
}

function followAfterMutate() {
  if (applying || scheduled) return
  scheduled = true
  const pinned = stickToBottom.value
  nextTick(() => {
    scheduled = false
    applying = true
    try {
      if (pinned) pinNow()
      else restoreLastAnchor()
    } finally {
      applying = false
    }
  })
}

onMounted(() => {
  const root = contentRef.value
  if (!root) return
  mo = new MutationObserver(followAfterMutate)
  mo.observe(root, { childList: true, subtree: true, characterData: true })
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(followAfterMutate)
    ro.observe(root)
  }
})

onUnmounted(() => {
  mo?.disconnect()
  ro?.disconnect()
  mo = null
  ro = null
})

defineExpose({ pinToBottom, wrapEl })
</script>

<style scoped>
.stick-scrollbar :deep(.el-scrollbar__wrap) {
  overflow-x: hidden;
}
</style>
