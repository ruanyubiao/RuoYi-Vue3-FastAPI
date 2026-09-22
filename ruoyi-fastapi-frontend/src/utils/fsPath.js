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
