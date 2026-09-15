/**
 * 实时 / 归档 / 文件曲线共用的滚轮缩放开关。
 * 页面不再各自缓存；切换页面保持同一组状态。
 */
import { ref, watch } from 'vue'
import cache from '@/plugins/cache'

const PREFS_KEY = 'payload:timeseries:zoomWheel:v1'
const LEGACY_KEYS = [
  'payload:curve:prefs:v1',
  'payload:archive:prefs:v1',
  'payload:fileCurve:prefs:v1'
]

function readPair(raw) {
  if (!raw || typeof raw !== 'object') return null
  const hasX = typeof raw.zoomX === 'boolean'
  const hasY = typeof raw.zoomY === 'boolean'
  if (!hasX && !hasY) return null
  return {
    zoomX: hasX ? raw.zoomX : true,
    zoomY: hasY ? raw.zoomY : false
  }
}

function loadPrefs() {
  const shared = readPair(cache.local.getJSON(PREFS_KEY, null))
  if (shared) return { pair: shared, persistNow: false }
  for (const key of LEGACY_KEYS) {
    const legacy = readPair(cache.local.getJSON(key, null))
    if (legacy) return { pair: legacy, persistNow: true }
  }
  return { pair: { zoomX: true, zoomY: false }, persistNow: false }
}

const loaded = loadPrefs()
export const zoomX = ref(loaded.pair.zoomX)
export const zoomY = ref(loaded.pair.zoomY)

function persist() {
  cache.local.setJSON(PREFS_KEY, {
    zoomX: !!zoomX.value,
    zoomY: !!zoomY.value
  })
}

if (loaded.persistNow) persist()

watch([zoomX, zoomY], persist)
