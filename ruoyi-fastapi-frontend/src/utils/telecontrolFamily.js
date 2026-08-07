/**
 * 从当前路由解析遥控项目族：biu | xl
 * 优先 query.family，其次路径段 /biu/ /xl/，再兼容旧扁平 controlXl/commandXl
 */
export function resolveTelecontrolFamily(route) {
  const q = String(route?.query?.family || '').toLowerCase()
  if (q === 'xl' || q === 'biu') return q
  const parts = String(route?.path || '')
    .toLowerCase()
    .split('/')
    .filter(Boolean)
  if (parts.includes('xl')) return 'xl'
  if (parts.includes('biu')) return 'biu'
  const last = parts[parts.length - 1] || ''
  if (last.includes('xl') && !last.includes('biu')) return 'xl'
  return 'biu'
}

/** 本族指令序列列表路径 */
export function sequenceListPath(family) {
  const f = family === 'xl' ? 'xl' : 'biu'
  return `/telecontrol/${f}/sequence`
}
