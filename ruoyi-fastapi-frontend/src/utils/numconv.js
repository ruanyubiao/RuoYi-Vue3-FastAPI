/**
 * 调试页数字转换：整数进制、数字与 HEX 互转。纯前端，不访问后端。
 * 进制字母表与 it-tools integer-base-converter 相同：0-9 a-z A-Z + /
 * 不超过 36 进制时大小写等价，输出大写；37–64 区分大小写。
 */

import { bytesToHex, hexToBytes } from '@/utils/payloadRawData'

const ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/'

export const NUM_TYPES = [
  { id: 'int8', label: 'int8', bits: 8, signed: true, kind: 'int' },
  { id: 'uint8', label: 'uint8', bits: 8, signed: false, kind: 'int' },
  { id: 'int16', label: 'int16', bits: 16, signed: true, kind: 'int' },
  { id: 'uint16', label: 'uint16', bits: 16, signed: false, kind: 'int' },
  { id: 'int24', label: 'int24', bits: 24, signed: true, kind: 'int' },
  { id: 'uint24', label: 'uint24', bits: 24, signed: false, kind: 'int' },
  { id: 'int32', label: 'int32', bits: 32, signed: true, kind: 'int' },
  { id: 'uint32', label: 'uint32', bits: 32, signed: false, kind: 'int' },
  { id: 'int48', label: 'int48', bits: 48, signed: true, kind: 'int' },
  { id: 'uint48', label: 'uint48', bits: 48, signed: false, kind: 'int' },
  { id: 'int56', label: 'int56', bits: 56, signed: true, kind: 'int' },
  { id: 'uint56', label: 'uint56', bits: 56, signed: false, kind: 'int' },
  { id: 'int64', label: 'int64', bits: 64, signed: true, kind: 'int' },
  { id: 'uint64', label: 'uint64', bits: 64, signed: false, kind: 'int' },
  { id: 'float', label: 'float', bits: 32, kind: 'float' },
  { id: 'double', label: 'double', bits: 64, kind: 'float' }
]

const INT_TEXT = /^[+-]?\d+$/
const FLOAT_TEXT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/

export function getNumType(id) {
  return NUM_TYPES.find(item => item.id === id) || null
}

function assertBase(base, label) {
  if (!Number.isInteger(base) || base < 2 || base > 64) {
    throw new Error(`${label}须在 2 到 64`)
  }
}

/** 非负整数进制转换。失败抛 Error。 */
export function convertBase(value, fromBase, toBase) {
  assertBase(fromBase, '输入进制')
  assertBase(toBase, '输出进制')
  const raw = String(value ?? '').replace(/\s+/g, '')
  if (!raw) throw new Error('请输入整数')
  const fromAlphabet = ALPHABET.slice(0, fromBase)
  const toAlphabet = ALPHABET.slice(0, toBase)
  let dec = 0n
  for (let i = 0; i < raw.length; i++) {
    const digit = raw[i]
    let idx = fromAlphabet.indexOf(digit)
    if (idx < 0 && fromBase <= 36) idx = fromAlphabet.indexOf(digit.toLowerCase())
    if (idx < 0) throw new Error(`数字「${digit}」不属于 ${fromBase} 进制`)
    const power = raw.length - 1 - i
    dec += BigInt(idx) * (BigInt(fromBase) ** BigInt(power))
  }
  if (dec === 0n) return '0'
  let out = ''
  while (dec > 0n) {
    out = toAlphabet[Number(dec % BigInt(toBase))] + out
    dec /= BigInt(toBase)
  }
  return toBase <= 36 ? out.toUpperCase() : out
}

/** 二进制从低位起每 4 位一组，组间加空格。复制时应去掉空格。 */
export function groupBinary(value) {
  const raw = String(value ?? '')
  if (raw.length <= 4) return raw
  const parts = []
  for (let i = raw.length; i > 0; i -= 4) {
    parts.push(raw.slice(Math.max(0, i - 4), i))
  }
  return parts.reverse().join(' ')
}

function intBounds(type) {
  const bits = BigInt(type.bits)
  if (!type.signed) return { min: 0n, max: (1n << bits) - 1n }
  const half = 1n << (bits - 1n)
  return { min: -half, max: half - 1n }
}

function parseIntegerText(text, type) {
  const raw = String(text ?? '').trim()
  if (!raw) return { error: '请输入数字' }
  if (!INT_TEXT.test(raw)) return { error: `${type.label} 只能输入整数` }
  let value
  try {
    value = BigInt(raw)
  } catch {
    return { error: `${type.label} 只能输入整数` }
  }
  const { min, max } = intBounds(type)
  if (value < min || value > max) {
    return { error: `${type.label} 的范围是 ${min} ~ ${max}` }
  }
  return { value }
}

function parseFloatText(text, type) {
  const raw = String(text ?? '').trim()
  if (!raw) return { error: '请输入数字' }
  if (/nan|inf/i.test(raw) || !FLOAT_TEXT.test(raw)) {
    return { error: `${type.label} 需要十进制或科学计数法，不能是 NaN / Infinity` }
  }
  const value = Number(raw)
  if (!Number.isFinite(value)) {
    return { error: `${type.label} 超出可表示范围` }
  }
  if (Object.is(value, 0) && raw.startsWith('-')) return { value: -0 }
  return { value }
}

function unsignedToBeBytes(value, bits) {
  const size = bits / 8
  const out = new Uint8Array(size)
  let rest = value
  for (let i = size - 1; i >= 0; i--) {
    out[i] = Number(rest & 0xffn)
    rest >>= 8n
  }
  return out
}

function floatToBeBytes(value, bits) {
  const size = bits / 8
  const buf = new ArrayBuffer(size)
  const view = new DataView(buf)
  if (bits === 32) view.setFloat32(0, value, false)
  else view.setFloat64(0, value, false)
  return new Uint8Array(buf)
}

function endianPair(beBytes) {
  const le = new Uint8Array(beBytes.length)
  for (let i = 0; i < beBytes.length; i++) le[i] = beBytes[beBytes.length - 1 - i]
  return { be: bytesToHex(beBytes), le: bytesToHex(le) }
}

/** 数字 → 大端/小端 HEX。失败返回 { error }。 */
export function numberToHex(text, typeId) {
  const type = getNumType(typeId)
  if (!type) return { error: '未知数字类型' }
  const parsed = type.kind === 'float' ? parseFloatText(text, type) : parseIntegerText(text, type)
  if (parsed.error) return { error: parsed.error }
  let beBytes
  if (type.kind === 'float') {
    beBytes = floatToBeBytes(parsed.value, type.bits)
  } else {
    let u = parsed.value
    if (type.signed && u < 0n) u += 1n << BigInt(type.bits)
    beBytes = unsignedToBeBytes(u, type.bits)
  }
  const hex = endianPair(beBytes)
  return { input: String(text ?? '').trim(), be: hex.be, le: hex.le }
}

function padToWidth(bytes, width, padTail) {
  if (bytes.length >= width) return bytes
  const out = new Uint8Array(width)
  if (padTail) out.set(bytes, 0)
  else out.set(bytes, width - bytes.length)
  return out
}

function formatFloat(value) {
  if (Object.is(value, -0)) return '-0'
  return String(value)
}

function readInteger(bytes, type, littleEndian) {
  const ordered = littleEndian ? [...bytes].reverse() : bytes
  let u = 0n
  for (const b of ordered) u = (u << 8n) | BigInt(b)
  if (type.signed) {
    const sign = 1n << BigInt(type.bits - 1)
    if (u >= sign) u -= 1n << BigInt(type.bits)
  }
  return u.toString(10)
}

function takeBytes(bytes, width, padTail) {
  if (bytes.length >= width) return bytes.slice(0, width)
  return padToWidth(bytes, width, padTail)
}

/**
 * HEX → 各类型。输入最多 8 字节。
 * 每种类型只取前面相应的字节；不够则按补零规则补齐。
 * 大端/小端列显示取出的字节，结果按所选端序解释这些字节。
 */
export function hexToNumberRows(hexText, { padTail = true, endian = 'be' } = {}) {
  const bytes = hexToBytes(hexText)
  if (!bytes || !bytes.length) return { error: '请输入 HEX' }
  if (bytes.length > 8) return { error: '超过8字节' }
  const littleEndian = endian === 'le'
  const rows = NUM_TYPES.map(type => {
    const slice = takeBytes(bytes, type.bits / 8, padTail)
    const pair = endianPair(slice)
    if (type.kind === 'float') {
      const view = new DataView(slice.buffer, slice.byteOffset, slice.byteLength)
      const value = type.bits === 32 ? view.getFloat32(0, littleEndian) : view.getFloat64(0, littleEndian)
      return { type: type.label, result: formatFloat(value), be: pair.be, le: pair.le }
    }
    return { type: type.label, result: readInteger(slice, type, littleEndian), be: pair.be, le: pair.le }
  })
  return { rows }
}
