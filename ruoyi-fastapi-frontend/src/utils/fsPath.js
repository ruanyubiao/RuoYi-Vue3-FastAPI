/**
 * 路径显示：Windows 盘符（E:/...）和 UNC 用反斜杠；其他系统路径保持原样。
 */
export function displayFsPath(path) {
  const s = String(path || '')
  if (/^[A-Za-z]:[\\/]/.test(s) || s.startsWith('\\\\') || s.startsWith('//')) {
    return s.replace(/\//g, '\\')
  }
  return s
}

/**
 * 兼容 Windows 文件名大小写不敏感：后缀先原样匹配，匹配不到再按小写匹配。
 */
export function fileExtAllowed(allowed, ext) {
  const list = Array.isArray(allowed) ? allowed : []
  if (list.indexOf(ext) >= 0) return true
  return list.indexOf(String(ext || '').toLowerCase()) >= 0
}

/**
 * 取路径最后一段：同时识别 '/' 与 Windows '\\'。
 */
export function baseNameAny(name) {
  const s = String(name ?? '')
  const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'))
  return i > -1 ? s.slice(i + 1) : s
}

/**
 * 相对路径上一级：同时识别 '/' 与 '\\'，结果统一用 '/'。
 */
export function parentRelPath(rel) {
  const parts = String(rel || '').replace(/\\/g, '/').split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}
