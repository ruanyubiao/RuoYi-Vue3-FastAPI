/** 遥测表下拉：文案、模糊筛选、XL/BIU 分组。 */

/** 分组展示：``XL-D8：相机慢遥测``；无 family 则不加前缀。 */
export function telemetryOptionLabel(p) {
  if (!p) return ''
  const fam = String(p.family || '').trim().toUpperCase()
  const prefix = fam ? `${fam}-` : ''
  const id = p.localKey || p.id || p.key || ''
  const name = p.name || ''
  return name ? `${prefix}${id}：${name}` : `${prefix}${id}`
}

/** 去掉空白与常见分隔符，便于 ``xl d8`` / ``相机慢`` 这类模糊筛选。 */
function foldText(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[\s\-_:：,，.。/\\|~～()（）[\]【】]/g, '')
}

/**
 * 遥测表下拉模糊匹配：忽略大小写与分隔符，空格分词后每段都要命中。
 * 匹配范围含展示文案、key、本地编号、名称、family。
 */
export function telemetryOptionMatch(query, p) {
  const raw = String(query || '').trim()
  if (!raw) return true
  if (!p) return false
  const hay = foldText(
    [
      p.label,
      telemetryOptionLabel(p),
      p.key,
      p.id,
      p.localKey,
      p.name,
      p.family
    ]
      .filter(Boolean)
      .join(' ')
  )
  const tokens = raw
    .toLowerCase()
    .split(/\s+/)
    .map(foldText)
    .filter(Boolean)
  return tokens.every(t => hay.includes(t))
}

/** 按筛选词过滤后分成 XL / BIU 组。keepKey 为当前选中项，避免筛掉后输入框丢文案。 */
export function groupTelemetryPages(pages, query = '', keepKey = '') {
  const keep = String(keepKey || '')
  const list = (pages || []).filter(p => {
    if (!p || !(p.key || p.id)) return false
    if (keep && (p.key === keep || p.id === keep)) return true
    return telemetryOptionMatch(query, p)
  })
  const xl = list.filter(p => (p.family || '') === 'xl')
  const biu = list.filter(p => (p.family || '') === 'biu')
  const other = list.filter(p => {
    const f = p.family || ''
    return f !== 'xl' && f !== 'biu'
  })
  return [
    { label: 'XL', options: xl },
    { label: 'BIU', options: biu },
    { label: '其他', options: other }
  ].filter(g => g.options.length)
}
