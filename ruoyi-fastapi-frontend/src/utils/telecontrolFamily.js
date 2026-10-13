/**
 * 从当前路由解析遥控项目族：biu | xl | yj216
 * 优先 query.family，其次路径段，再兼容旧扁平 controlXl/commandXl
 */
export function resolveTelecontrolFamily(route) {
  const q = String(route?.query?.family || '').toLowerCase()
  if (q === 'xl' || q === 'biu' || q === 'yj216') return q
  const parts = String(route?.path || '')
    .toLowerCase()
    .split('/')
    .filter(Boolean)
  if (parts.includes('yj216')) return 'yj216'
  if (parts.includes('xl')) return 'xl'
  if (parts.includes('biu')) return 'biu'
  const last = parts[parts.length - 1] || ''
  if (last.includes('xl') && !last.includes('biu')) return 'xl'
  return 'biu'
}

/** 配置没有 page 时，用全部指令合成一页，否则左侧树是空的。 */
export function telecontrolPages(data) {
  const pages = Array.isArray(data?.page) ? data.page : []
  if (pages.length) return pages
  const orders = data?.order && typeof data.order === 'object' ? data.order : {}
  const orderList = Object.keys(orders)
  if (!orderList.length) return []
  return [{ id: 'all', name: '遥控', orderList }]
}

/** 本族指令序列列表路径 */
export function sequenceListPath(family) {
  const f = family === 'xl' ? 'xl' : family === 'yj216' ? 'yj216' : 'biu'
  return `/${f}/telecontrol/sequence`
}
