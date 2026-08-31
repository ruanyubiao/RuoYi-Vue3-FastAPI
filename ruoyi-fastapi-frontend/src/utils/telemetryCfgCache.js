/**
 * 遥测表配置缓存：scope 键 + 服务端 cfgDatetime/cfgMtime 版本失效。
 * TTL 由 cache.expire 负责（默认 1 小时）。
 */

import cache from '@/plugins/cache'

const PREFIX = 'payload:tmCfg:v1:'
/** 无时间戳时的兜底 TTL（默认 1 小时） */
export const TM_CFG_TTL_MS = 60 * 60 * 1000

function storageKey(scope) {
  return `${PREFIX}${String(scope || '').trim()}`
}

function ttlSec(ttlMs) {
  return Math.max(1, Math.ceil((ttlMs || TM_CFG_TTL_MS) / 1000))
}

/**
 * @param {string} scope 如 camera:D8 / tm:D8
 */
export function takeTelemetryCfg(scope, { cfgDatetime, cfgMtime } = {}) {
  if (!scope) return null
  const key = storageKey(scope)
  const obj = cache.expire.getJSON(key)
  if (!obj || typeof obj !== 'object') return null
  const stampDt = String(cfgDatetime || '').trim()
  const stampMt = String(cfgMtime || '').trim()
  if (stampDt || stampMt) {
    const cachedDt = String(obj.cfgDatetime || '').trim()
    const cachedMt = String(obj.cfgMtime || '').trim()
    if ((stampDt && cachedDt && stampDt !== cachedDt) || (stampMt && cachedMt && stampMt !== cachedMt)) {
      cache.expire.remove(key)
      return null
    }
    if (!cachedDt && !cachedMt) {
      cache.expire.remove(key)
      return null
    }
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
}

export function saveTelemetryCfg(scope, data, { ttlMs = TM_CFG_TTL_MS } = {}) {
  if (!scope || !data) return
  const cfgRows = data.cfgRows || data.cfg?.row || []
  if (!Array.isArray(cfgRows) || !cfgRows.length) return
  cache.expire.setJSON(
    storageKey(scope),
    {
      name: data.name || data.cfgName || '',
      tableKey: data.tableKey || '',
      pages: Array.isArray(data.pages) ? data.pages : [],
      cfgRows,
      cfgName: data.cfgName || data.cfg?.name || data.name || '',
      cfgDatetime: data.cfgDatetime || '',
      cfgMtime: data.cfgMtime || ''
    },
    ttlSec(ttlMs)
  )
}

export function clearTelemetryCfg(scope) {
  if (!scope) return
  cache.expire.remove(storageKey(scope))
}

export function clearAllTelemetryCfg() {
  for (const k of cache.expire.keys(PREFIX)) {
    cache.expire.remove(k)
  }
}

export function cameraTmCfgScope(tableKey = 'D8') {
  return `camera:${String(tableKey || 'D8').toUpperCase()}`
}

export function xlBoardTmCfgScope(board) {
  return `xl:${String(board || '').toLowerCase()}`
}

export function tmTypeCfgScope(tableType) {
  return `tm:${String(tableType || '').toUpperCase()}`
}

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
