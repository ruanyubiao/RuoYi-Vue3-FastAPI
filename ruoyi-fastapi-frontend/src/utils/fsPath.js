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
 * 回放选文件展示路径：去掉系统盘符/根，改成首页虚拟路径。
 *
 * 例：
 * - .../upload_logs_data_raw/a.bin → 首页/上传文件/a.bin
 * - .../logs_data/raw/2026/09/18/a.bin → 首页/本地日志/2026/09/18/a.bin
 *
 * 内部仍保存绝对路径；仅用于输入框等展示。已是「首页/...」则原样返回。
 */
export function toRecvBrowseDisplayPath(path) {
  const raw = String(path || '').trim()
  if (!raw) return ''
  const s = raw.replace(/\\/g, '/')
  if (s.startsWith('首页/') || s === '首页') return s.replace(/\/+/g, '/')

  const uploadKey = 'upload_logs_data_raw'
  const ui = s.indexOf(uploadKey)
  if (ui >= 0) {
    const rest = s.slice(ui + uploadKey.length).replace(/^\/+/, '')
    return rest ? `首页/上传文件/${rest}` : '首页/上传文件'
  }

  const logsKey = 'logs_data/raw'
  const li = s.indexOf(logsKey)
  if (li >= 0) {
    const rest = s.slice(li + logsKey.length).replace(/^\/+/, '')
    return rest ? `首页/本地日志/${rest}` : '首页/本地日志'
  }

  return displayFsPath(raw)
}

/**
 * 由浏览 root/相对目录/文件名拼展示路径（与选中时一致）。
 */
export function buildRecvBrowseDisplayPath(root, rel, name) {
  const rootLabel = root === 'upload' ? '上传文件' : root === 'logs' ? '本地日志' : ''
  if (!rootLabel) return name ? String(name) : ''
  const parts = ['首页', rootLabel]
  const relParts = String(rel || '')
    .replace(/\\/g, '/')
    .split('/')
    .filter(Boolean)
  parts.push(...relParts)
  if (name) parts.push(String(name))
  return parts.join('/')
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
