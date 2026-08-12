/**
 * 遥测表配置缓存（编号/名称/单位等），无实时数据时也能快速画出空表。
 * 使用 localStorage；用服务端 cfgDatetime / cfgMtime 判定是否过期（Ctrl+F5 清不掉）。
 */

const PREFIX = 'payload:tmCfg:v1:'
/** 无时间戳时的兜底 TTL（默认 1 小时） */
export const TM_CFG_TTL_MS = 60 * 60 * 1000

function now() {
  return Date.now()
}

function storageKey(scope) {
  return `${PREFIX}${String(scope || '').trim()}`
}

/**
 * @param {string} scope 如 camera:D8 / tm:D8
 * @returns {{ name?: string, tableKey?: string, pages?: any[], cfgRows?: any[], cfgName?: string, cfgDatetime?: string, cfgMtime?: string } | null}
 */
export function takeTelemetryCfg(scope, { maxAgeMs = TM_CFG_TTL_MS, cfgDatetime, cfgMtime } = {}) {
  if (!scope) return null
  try {
    const raw = localStorage.getItem(storageKey(scope))
    if (!raw) return null
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object') return null
    const stampDt = String(cfgDatetime || '').trim()
    const stampMt = String(cfgMtime || '').trim()
    // 服务端给出的时间戳与缓存不一致 → 视为过期
    if (stampDt || stampMt) {
      const cachedDt = String(obj.cfgDatetime || '').trim()
      const cachedMt = String(obj.cfgMtime || '').trim()
      if ((stampDt && cachedDt && stampDt !== cachedDt) || (stampMt && cachedMt && stampMt !== cachedMt)) {
        localStorage.removeItem(storageKey(scope))
        return null
      }
      // 服务端有戳、本地无戳：旧缓存，作废
      if ((stampDt || stampMt) && !cachedDt && !cachedMt) {
        localStorage.removeItem(storageKey(scope))
        return null
      }
    }
    const expiresAt = Number(obj.expiresAt) || 0
    if (expiresAt && now() > expiresAt) {
      localStorage.removeItem(storageKey(scope))
      return null
    }
    const at = Number(obj.at) || 0
    if (!stampDt && !stampMt && at && maxAgeMs > 0 && now() - at > maxAgeMs) {
      localStorage.removeItem(storageKey(scope))
      return null
    }
    return {
      name: obj.name || '',
      tableKey: obj.tableKey || '',
      pages: Array.isArray(obj.pages) ? obj.pages : [],
      cfgRows: Array.isArray(obj.cfgRows) ? obj.cfgRows : [],
      cfgName: obj.cfgName || '',
      cfgDatetime: obj.cfgDatetime || '',
      cfgMtime: obj.cfgMtime || ''
    }
  } catch {
    return null
  }
}

/**
 * @param {string} scope
 * @param {{ name?: string, tableKey?: string, pages?: any[], cfgRows?: any[], cfgName?: string, cfgDatetime?: string, cfgMtime?: string, cfg?: any }} data
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
        cfgName: data.cfgName || data.cfg?.name || data.name || '',
        cfgDatetime: data.cfgDatetime || '',
        cfgMtime: data.cfgMtime || ''
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

/** 清空全部遥测表配置缓存（配置热重载后调用） */
export function clearAllTelemetryCfg() {
  try {
    const keys = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(PREFIX)) keys.push(k)
    }
    keys.forEach(k => localStorage.removeItem(k))
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

/** 通用遥测表组件缓存 scope（按 dataSub / type） */
export function tmTypeCfgScope(tableType) {
  return `tm:${String(tableType || '').toUpperCase()}`
}

/** 缓存时间戳是否与服务端不一致（需重新拉 cfg） */
export function isTelemetryCfgStale(scope, { cfgDatetime, cfgMtime } = {}) {
  const stampDt = String(cfgDatetime || '').trim()
  const stampMt = String(cfgMtime || '').trim()
  if (!stampDt && !stampMt) return false
  const cached = takeTelemetryCfg(scope)
  if (!cached?.cfgRows?.length) return true
  const cachedDt = String(cached.cfgDatetime || '').trim()
  const cachedMt = String(cached.cfgMtime || '').trim()
  if (stampMt && cachedMt && stampMt !== cachedMt) return true
  if (stampDt && cachedDt && stampDt !== cachedDt) return true
  if (!cachedDt && !cachedMt) return true
  return false
}
