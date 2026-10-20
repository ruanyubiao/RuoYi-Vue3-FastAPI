/** 给带图标的按钮打标，loading 时转圈留在原图标位置，按钮尺寸不变。 */

function hasContentIcon(btn) {
  return [...btn.children].some(
    (el) => el.classList?.contains('el-icon') && !el.classList.contains('is-loading'),
  )
}

function markOne(btn) {
  if (btn.dataset.hasIcon === '1') return
  if (hasContentIcon(btn)) btn.dataset.hasIcon = '1'
}

export function markIconButtons(root) {
  if (!root || root.nodeType !== 1) return
  if (root.classList?.contains('el-button')) markOne(root)
  root.querySelectorAll?.('.el-button').forEach(markOne)
}

export function installButtonIconMark(root = document.body) {
  if (!root) return
  const observer = new MutationObserver((records) => {
    records.forEach((record) => {
      if (record.target?.nodeType === 1) markIconButtons(record.target)
      record.addedNodes.forEach((node) => {
        if (node.nodeType === 1) markIconButtons(node)
      })
    })
  })
  observer.observe(root, { childList: true, subtree: true })
  markIconButtons(root)
  return observer
}
