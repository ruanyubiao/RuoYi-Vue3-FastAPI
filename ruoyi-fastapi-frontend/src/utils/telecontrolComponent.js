/**
 * 遥控 component UI 规则（与后端 encode 分离）：
 * - dataTypeUI 优先，否则 dataType（旧配置兼容）
 * - minVal/maxVal 空串不限制
 * - stepVal 可选；有合法正数则作 number 步进，否则浮点 0.1 / 整数 1
 * - formula 只在组帧时计算，序列保存/还原的是输入控件原值
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
  const step = numBound(comp?.stepVal)
  if (step !== undefined && step > 0) return step
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

/** 遥控 component 表单项标题 */
export function componentLabel(comp, index = 0) {
  const title = String(comp?.title || comp?.name || '').trim()
  if (title) return title
  return `参数${Number(index) + 1}`
}

/** 遥控 component 表单项 tooltip；空串表示不显示 */
export function componentTip(comp) {
  return String(comp?.tip || '').trim()
}

/** 遥控指令对象 tooltip；空串表示不显示（不参与搜索筛选） */
export function orderTip(order) {
  return String(order?.tip || '').trim()
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

const MASK_BITS = {
  INT8: 8,
  UINT8: 8,
  BYTE: 8,
  INT16: 16,
  UINT16: 16,
  INT24: 24,
  UINT24: 24,
  INT32: 32,
  UINT32: 32,
  INT40: 40,
  UINT40: 40,
  INT48: 48,
  UINT48: 48,
  INT56: 56,
  UINT56: 56,
  INT64: 64,
  UINT64: 64
}

/** dataType 对应的位图位数。INT* 与 UINT* 同宽。 */
export function checkboxMaskBits(comp) {
  const dt = String(comp?.dataType || '').trim().toUpperCase()
  return MASK_BITS[dt] || 0
}

/**
 * 读勾选位图。
 * 与 dataType 等宽、只含 0/1 的字符串按位读取，左边是高位，最右边是 group[0]。
 * 旧的数字或十进制字符串仍可还原。
 */
export function parseCheckboxMask(raw, bits) {
  const width = Number(bits) || 0
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (/^[01]+$/.test(s) && s.length === width) return BigInt(`0b${s}`)
    if (/^\d+$/.test(s)) return BigInt(s)
    return 0n
  }
  if (typeof raw === 'bigint') return raw >= 0n ? raw : 0n
  if (typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= 0) return BigInt(raw)
  return 0n
}

/** 写成与 dataType 等宽的 0/1 字符串。 */
export function formatCheckboxMask(mask, bits) {
  const width = Number(bits) || 0
  if (width <= 0) return ''
  let value = typeof mask === 'bigint' ? (mask >= 0n ? mask : 0n) : parseCheckboxMask(mask, width)
  const limit = 1n << BigInt(width)
  if (value >= limit) value &= limit - 1n
  return value.toString(2).padStart(width, '0')
}

/** checkboxgroup 的初值：mask 为 0，子控件按各自默认值。 */
export function emptyCheckboxGroupValue(comp) {
  const group = Array.isArray(comp?.group) ? comp.group : []
  return {
    mask: formatCheckboxMask(0n, checkboxMaskBits(comp)),
    values: group.map((item) => {
      const children = Array.isArray(item?.component) ? item.component : []
      return children.map((child) => resolveComponentValue(child))
    })
  }
}

/** 按配置默认值解析单个 component 的 UI 初值 */
export function resolveComponentValue(comp) {
  const type = (comp.componentType || '').toLowerCase()
  const raw = comp.defaultVal
  if (type === 'checkboxgroup') return emptyCheckboxGroupValue(comp)
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
 * 把已保存的输入值套到当前控件规则上。
 * 控件删了/类型变了/选项没了对不上 → 用最新 default；数值超出 min/max → 钳到范围内。
 */
export function coerceSavedCompValue(comp, saved) {
  const fallback = resolveComponentValue(comp)
  const type = (comp?.componentType || '').toLowerCase()
  if (type === 'checkboxgroup') {
    const group = Array.isArray(comp?.group) ? comp.group : []
    const bits = checkboxMaskBits(comp)
    const savedMask = saved && typeof saved === 'object' ? saved.mask : 0
    const mask = formatCheckboxMask(parseCheckboxMask(savedMask, bits), bits)
    const rows = saved && typeof saved === 'object' && Array.isArray(saved.values) ? saved.values : []
    return {
      mask,
      values: group.map((item, i) => {
        const children = Array.isArray(item?.component) ? item.component : []
        const row = Array.isArray(rows[i]) ? rows[i] : []
        return children.map((child, j) => coerceSavedCompValue(child, row[j]))
      })
    }
  }
  if (type === 'fixed') return fallback
  if (saved === undefined || saved === null || saved === '') return fallback

  if (type === 'select') {
    const options = comp.options || {}
    const str = String(saved)
    if (Object.prototype.hasOwnProperty.call(options, str)) return str
    for (const [key, label] of Object.entries(options)) {
      if (String(label) === str) return key
    }
    return fallback
  }

  if (type === 'number' || type === 'scientific') {
    const num = Number(saved)
    if (!Number.isFinite(num)) return fallback
    let val = type === 'number' && isIntegerDataType(comp) ? Math.trunc(num) : num
    const min = numBound(comp.minVal)
    const max = numBound(comp.maxVal)
    if (min !== undefined && val < min) val = min
    if (max !== undefined && val > max) val = max
    return type === 'scientific' ? String(val) : val
  }

  return String(saved)
}

/**
 * 还原指令参数：按当前 component 列表对齐已保存的输入控件值（含带 formula 的项）。
 */
export function resolveCompValuesForOrder(order, savedValues) {
  const comps = order?.component || []
  const saved = Array.isArray(savedValues) ? savedValues : []
  return comps.map((comp, index) => coerceSavedCompValue(comp, saved[index]))
}
