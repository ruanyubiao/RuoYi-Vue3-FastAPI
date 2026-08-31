/**
 * 浏览器 KV 统一入口。业务代码禁止直写 localStorage / sessionStorage。
 *
 * 分层：
 * - Pinia：运行时状态（刷新丢失）
 * - cache.session：当前标签页会话（防重复提交、传输加密、刷新信号）
 * - cache.local：持久偏好（无 TTL），键名建议 payload:<域>:<用途>:v1
 * - cache.expire：带过期时间的本地缓存，TTL 单位秒
 *
 * Options API：this.$cache（plugins/index.js 已注册）
 * 工具模块：import cache, { fillDefaults, normalizeRecord } from '@/plugins/cache'
 *
 * JSON 默认值两层：getJSON(key, default) 管整对象；字段转换用 fillDefaults / normalizeRecord。
 */

const MAX_EXPIRE_MS = new Date('Fri, 31 Dec 9999 23:59:59 UTC').getTime()

function safeParse(raw, fallback = null) {
  if (raw == null || raw === '') return fallback
  try {
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

function expireAtMs(expSec) {
  if (expSec == null || expSec === Infinity) return MAX_EXPIRE_MS
  return Date.now() + Number(expSec) * 1000
}

function isExpireWrapper(obj) {
  return obj && typeof obj === 'object' && 'c' in obj && 'e' in obj && 'v' in obj
}

/**
 * 浅合并：raw 中 undefined 的键用 defaults 补上（null 保留）。
 */
export function fillDefaults(raw, defaults) {
  const out = { ...defaults }
  if (!raw || typeof raw !== 'object') return out
  for (const key of Object.keys(defaults)) {
    if (raw[key] !== undefined) out[key] = raw[key]
  }
  return out
}

/**
 * 按字段规格归一化：spec 的 value 为 (v, raw) => 转换后的值。
 */
export function normalizeRecord(raw, spec, defaults = {}) {
  const base = fillDefaults(raw, defaults)
  const out = {}
  for (const [key, coerce] of Object.entries(spec)) {
    out[key] = coerce(base[key], base)
  }
  return out
}

function createKvCache(storage) {
  return {
    set(key, value) {
      if (!storage || key == null) return
      if (value == null) {
        storage.removeItem(key)
        return
      }
      try {
        storage.setItem(key, value)
      } catch {
        /* quota / private mode */
      }
    },
    get(key, defaultValue = null) {
      if (!storage || key == null) return defaultValue
      try {
        const raw = storage.getItem(key)
        return raw == null ? defaultValue : raw
      } catch {
        return defaultValue
      }
    },
    setJSON(key, jsonValue) {
      if (jsonValue == null) {
        this.remove(key)
        return
      }
      this.set(key, JSON.stringify(jsonValue))
    },
    getJSON(key, defaultValue = null) {
      const value = this.get(key)
      if (value == null || value === '') return defaultValue
      return safeParse(value, defaultValue)
    },
    remove(key) {
      if (!storage || key == null) return
      try {
        storage.removeItem(key)
      } catch {
        /* ignore */
      }
    },
    keys(prefix = '') {
      if (!storage) return []
      const out = []
      try {
        for (let i = 0; i < storage.length; i++) {
          const k = storage.key(i)
          if (k && k.startsWith(prefix)) out.push(k)
        }
      } catch {
        /* ignore */
      }
      return out
    }
  }
}

const sessionCache = createKvCache(typeof sessionStorage !== 'undefined' ? sessionStorage : null)
const localCache = createKvCache(typeof localStorage !== 'undefined' ? localStorage : null)

const expireLocalCache = {
  set(key, value, exp) {
    if (key == null) return
    if (value == null) {
      localCache.remove(key)
      return
    }
    const wrapper = {
      c: Date.now(),
      e: expireAtMs(exp),
      v: JSON.stringify(value)
    }
    localCache.setJSON(key, wrapper)
  },
  get(key, defaultValue = null) {
    const wrapper = localCache.getJSON(key)
    if (!isExpireWrapper(wrapper)) return defaultValue
    if (Date.now() >= wrapper.e) {
      localCache.remove(key)
      return defaultValue
    }
    const parsed = safeParse(wrapper.v, undefined)
    return parsed === undefined ? defaultValue : parsed
  },
  setJSON(key, jsonValue, exp) {
    this.set(key, jsonValue, exp)
  },
  getJSON(key, defaultValue = null) {
    return this.get(key, defaultValue)
  },
  remove(key) {
    localCache.remove(key)
  },
  keys(prefix = '') {
    return localCache.keys(prefix)
  }
}

export default {
  /** 会话级缓存 → sessionStorage */
  session: sessionCache,
  /** 本地缓存 → localStorage */
  local: localCache,
  /** 支持过期时间的本地缓存 → localStorage（TTL 单位：秒） */
  expire: expireLocalCache
}
