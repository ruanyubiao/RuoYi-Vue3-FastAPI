/** 连接对话框：解析器/组装器列表、使用|打开、already_open 文案。 */

import { listParsers, listAssemblers } from '@/api/payload/device'

export function mapPipelineOptions(list) {
  if (!Array.isArray(list)) return []
  return list
    .map(item => {
      if (typeof item === 'string') return { id: item, name: item }
      const id = item?.id || item?.parserId || item?.assemblerId
      if (!id) return null
      return { id, name: item.name || item.label || id }
    })
    .filter(Boolean)
}

export async function loadParserOptions(fallback = []) {
  try {
    const res = await listParsers()
    return mapPipelineOptions(res.data?.parsers || res.data || [])
  } catch {
    return [...fallback]
  }
}

export async function loadAssemblerOptions(srcKind, fallback = []) {
  try {
    const res = await listAssemblers(srcKind)
    return mapPipelineOptions(res.data?.assemblers || res.data || [])
  } catch {
    return [...fallback]
  }
}

export function confirmOpenLabel(canReuse) {
  return canReuse ? '使用' : '打开'
}

export function isAlreadyOpen(res) {
  return res?.data?.status === 'already_open'
}

export function reuseSuccessMessage(kind) {
  if (kind === 'can') return '已使用现有can卡并绑定本页参数'
  if (kind === 'serial') return '已使用现有串口并绑定本页参数'
  if (kind === 'udp') return '已使用现有UDP连接并绑定本页参数'
  return '已使用现有连接并绑定本页参数'
}
