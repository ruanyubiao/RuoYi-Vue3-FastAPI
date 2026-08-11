/**
 * 遥控 component UI 规则（与后端 encode 分离）：
 * - dataTypeUI 优先，否则 dataType（旧配置兼容）
 * - minVal/maxVal 空串不限制
 * - formula 非空时无法从 hex 反推 UI 原值，还原用 defaultVal
 */

export function uiDataType(comp) {
  const ui = String(comp?.dataTypeUI || '').trim()
  return (ui || comp?.dataType || 'INT16').toUpperCase()
}

export function isFloatUi(comp) {
  const dt = uiDataType(comp)
  return dt === 'FLOAT' || dt === 'DOUBLE'
}

export function isIntegerDataType(dataTypeOrComp) {
  const dt =
    typeof dataTypeOrComp === 'string'
      ? String(dataTypeOrComp || '').toUpperCase()
      : uiDataType(dataTypeOrComp)
  return !['FLOAT', 'DOUBLE'].includes(dt)
}

export function numberPrecision(comp) {
  return isFloatUi(comp) ? 6 : 0
}

export function numberStep(comp) {
  return isFloatUi(comp) ? 0.1 : 1
}

/** minVal/maxVal 空字符串 → undefined（不限制） */
export function numBound(v) {
  if (v === '' || v === null || v === undefined) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

export function hasFormula(comp) {
  return !!(comp?.formula && String(comp.formula).trim())
}

function resolveSelectDefault(comp) {
  const options = comp.options || {}
  const keys = Object.keys(options)
  const raw = comp.defaultVal
  if (raw !== '' && raw !== null && raw !== undefined) {
    const str = String(raw)
    if (Object.prototype.hasOwnProperty.call(options, str)) return str
  }
  return keys[0] ?? ''
}

/** 按配置默认值解析单个 component 的 UI 初值 */
export function resolveComponentValue(comp) {
  const type = (comp.componentType || '').toLowerCase()
  const raw = comp.defaultVal
  if (type === 'number') {
    if (raw === '' || raw === null || raw === undefined) return 0
    const num = Number(raw)
    const val = Number.isFinite(num) ? num : 0
    return isIntegerDataType(comp) ? Math.trunc(val) : val
  }
  if (type === 'select') return resolveSelectDefault(comp)
  if (type === 'scientific') return raw === '' || raw == null ? '0' : String(raw)
  if (raw === '' || raw === null || raw === undefined) return ''
  return String(raw)
}

/**
 * 还原指令参数：无 formula 时优先用已保存 UI 值；
 * 有 formula 时无法从 hex 反推原值，统一用配置 defaultVal（不依赖列表里可能残留的编码值）。
 */
export function resolveCompValuesForOrder(order, savedValues) {
  const comps = order?.component || []
  return comps.map((comp, index) => {
    if (hasFormula(comp)) {
      return resolveComponentValue(comp)
    }
    if (!Array.isArray(savedValues) || !savedValues.length) {
      return resolveComponentValue(comp)
    }
    const saved = savedValues[index]
    if (saved === undefined || saved === null || saved === '') {
      return resolveComponentValue(comp)
    }
    return saved
  })
}
