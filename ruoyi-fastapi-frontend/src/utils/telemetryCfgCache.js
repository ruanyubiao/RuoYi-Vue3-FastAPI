/**
 * 遥测表配置缓存（编号/名称/单位等），无实时数据时也能快速画出空表。
 * 使用 localStorage，带有效期。
 */

const PREFIX = 'payload:tmCfg:v1:'
/** 默认 1 小时；配置文件很少改 */
export const TM_CFG_TTL_MS = 60 * 60 * 1000

function now() {
  return Date.now()
}

function storageKey(scope) {
  return `${PREFIX}${String(scope || '').trim()}`
}

/**
 * @param {string} scope 如 camera:D8 / camera:D9 / rkdj / zk
 * @returns {{ name?: string, tableKey?: string, pages?: any[], cfgRows?: any[], cfgName?: string } | null}
 */
export function takeTelemetryCfg(scope, { maxAgeMs = TM_CFG_TTL_MS } = {}) {
  if (!scope) return null
  try {
    const raw = localStorage.getItem(storageKey(scope))
    if (!raw) return null
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object') return null
    const expiresAt = Number(obj.expiresAt) || 0
    if (expiresAt && now() > expiresAt) {
      localStorage.removeItem(storageKey(scope))
      return null
    }
    const at = Number(obj.at) || 0
    if (at && maxAgeMs > 0 && now() - at > maxAgeMs) {
      localStorage.removeItem(storageKey(scope))
      return null
    }
    return {
      name: obj.name || '',
      tableKey: obj.tableKey || '',
      pages: Array.isArray(obj.pages) ? obj.pages : [],
      cfgRows: Array.isArray(obj.cfgRows) ? obj.cfgRows : [],
      cfgName: obj.cfgName || ''
    }
  } catch {
    return null
  }
}

/**
 * @param {string} scope
 * @param {{ name?: string, tableKey?: string, pages?: any[], cfgRows?: any[], cfgName?: string }} data
 */
export function saveTelemetryCfg(scope, data, { ttlMs = TM_CFG_TTL_MS } = {}) {
  if (!scope || !data) return
  const cfgRows = data.cfgRows || data.cfg?.row || []
  if (!Array.isArray(cfgRows) || !cfgRows.length) return
  try {
    const at = now()
    localStorage.setItem(
      storageKey(scope),
      JSON.stringify({
        at,
        expiresAt: at + ttlMs,
        name: data.name || data.cfgName || '',
        tableKey: data.tableKey || '',
        pages: Array.isArray(data.pages) ? data.pages : [],
        cfgRows,
        cfgName: data.cfgName || data.cfg?.name || data.name || ''
      })
    )
  } catch {
    /* quota */
  }
}

export function clearTelemetryCfg(scope) {
  if (!scope) return
  try {
    localStorage.removeItem(storageKey(scope))
  } catch {
    /* ignore */
  }
}

export function cameraTmCfgScope(tableKey = 'D8') {
  return `camera:${String(tableKey || 'D8').toUpperCase()}`
}

export function xlBoardTmCfgScope(board) {
  return `xl:${String(board || '').toLowerCase()}`
}
