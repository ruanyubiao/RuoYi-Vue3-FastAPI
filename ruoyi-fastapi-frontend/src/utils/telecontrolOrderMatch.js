/**
 * 遥控指令搜索匹配（BIU/XL 遥控、指令序列、单板/相机共用）。
 * 规则：空格分词，每个词都需命中；命中范围 = id + name + 各 component.title。
 */

export function getFilterKeywords(text) {
  return String(text || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
}

export function matchesAllKeywords(text, keywords) {
  if (!keywords.length) return true
  const hay = String(text || '').toLowerCase()
  return keywords.every(kw => hay.includes(String(kw).toLowerCase()))
}

/** 拼出可搜索文本：指令代号、名称、各参数 title */
export function orderSearchText(order) {
  const parts = [order?.id || '', order?.name || '']
  for (const comp of order?.component || []) {
    const title = comp?.title
    if (title !== undefined && title !== null && String(title).trim() !== '') {
      parts.push(String(title))
    }
  }
  return parts.join(' ')
}

export function orderMatchesKeywords(order, keywords) {
  return matchesAllKeywords(orderSearchText(order), keywords)
}

export function orderMatchesFilter(order, filterText) {
  return orderMatchesKeywords(order, getFilterKeywords(filterText))
}
