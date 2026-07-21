/** 串口/UDP 等原始数据发送：HEX / 转义 / 行尾 共用工具 */

export const HEX_INPUT_WARN = '当前在十六进制输入模式下，只能输入十六进制形式的字符。'

export const LINE_ENDING_OPTIONS = [
  { label: '无追加', value: 'none' },
  { label: '\\n', value: 'lf' },
  { label: '\\r', value: 'cr' },
  { label: '\\r\\n', value: 'crlf' }
]

const SERIAL_LINE_ENDING_SUFFIX = {
  lf: '\n',
  cr: '\r',
  crlf: '\r\n'
}

function _padOddHex(cleaned) {
  if (!cleaned) return ''
  if (cleaned.length % 2 === 0) return cleaned
  return cleaned.slice(0, -1) + '0' + cleaned.slice(-1)
}

function _hexTokens(text) {
  if (!text) return []
  return String(text).trim().split(/\s+/).filter(Boolean)
}

function _normalizeHexPairsFromTokens(tokens) {
  const pairs = []
  for (const t of tokens) {
    if (!/^[0-9a-fA-F]+$/.test(t)) return null
    const padded = _padOddHex(t)
    const segs = padded.match(/.{1,2}/g) || []
    for (const s of segs) pairs.push(s.toUpperCase())
  }
  return pairs
}

export function cleanHex(text) {
  return (text || '').replace(/[^0-9a-fA-F]/g, '')
}

export function isHexText(text, { input = false } = {}) {
  if (!text || !text.trim()) return true
  if (!/^[0-9a-fA-F\s]+$/.test(text)) return false
  if (input) return true
  const normalized = normalizeHexDisplay(text)
  return /^([0-9a-fA-F]{2})(\s*[0-9a-fA-F]{2})*$/.test(normalized)
}

export function normalizeHexDisplay(text) {
  const tokens = _hexTokens(text)
  if (!tokens.length) return ''
  const pairs = _normalizeHexPairsFromTokens(tokens)
  if (!pairs) return ''
  return pairs.join(' ')
}

export function bytesToHex(bytes) {
  return Array.from(bytes)
    .map(b => b.toString(16).padStart(2, '0'))
    .join(' ')
    .toUpperCase()
}

export function textToHex(text) {
  return bytesToHex(new TextEncoder().encode(text || ''))
}

export function hexToBytes(hexText) {
  const pairs = _normalizeHexPairsFromTokens(_hexTokens(hexText))
  if (!pairs) return null
  return new Uint8Array(pairs.map(p => parseInt(p, 16)))
}

/** 可从 HEX 转回文本框：可打印 ASCII + Tab / CR / LF（多行框可显示换行） */
function isTextInputByte(byte) {
  if (byte >= 32 && byte <= 126) return true
  return byte === 0x09 || byte === 0x0a || byte === 0x0d
}

export function hexToPrintableText(hexText) {
  const pairs = _normalizeHexPairsFromTokens(_hexTokens(hexText))
  if (!pairs) return { ok: false, text: '' }
  let text = ''
  for (const p of pairs) {
    const byte = parseInt(p, 16)
    if (!isTextInputByte(byte)) return { ok: false, text: '' }
    text += String.fromCharCode(byte)
  }
  return { ok: true, text }
}

/** 显示用：尽量 UTF-8，失败则 latin1 */
export function hexToDisplayAscii(hexText) {
  const bytes = hexToBytes(hexText)
  if (!bytes) return ''
  try {
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  } catch {
    let s = ''
    for (const b of bytes) s += String.fromCharCode(b)
    return s
  }
}

/**
 * 解析转义为原始字节。
 * \xHH / \r\n\t\0\\ → 单字节；其余字符按 UTF-8 编码（避免 \xAA 变成 C2 AA）
 */
export function parseEscapeToBytes(text) {
  const out = []
  const enc = new TextEncoder()
  let i = 0
  const s = String(text || '')
  while (i < s.length) {
    if (s[i] === '\\' && i + 1 < s.length) {
      const next = s[i + 1]
      if (next === 'r') {
        out.push(0x0d)
        i += 2
        continue
      }
      if (next === 'n') {
        out.push(0x0a)
        i += 2
        continue
      }
      if (next === 't') {
        out.push(0x09)
        i += 2
        continue
      }
      if (next === '\\') {
        out.push(0x5c)
        i += 2
        continue
      }
      if (next === '0') {
        out.push(0x00)
        i += 2
        continue
      }
      if ((next === 'x' || next === 'X') && i + 3 < s.length) {
        const hex = s.slice(i + 2, i + 4)
        if (/^[0-9a-fA-F]{2}$/.test(hex)) {
          out.push(parseInt(hex, 16))
          i += 4
          continue
        }
      }
    }
    const cp = s.codePointAt(i)
    out.push(...enc.encode(String.fromCodePoint(cp)))
    i += cp > 0xffff ? 2 : 1
  }
  return new Uint8Array(out)
}

/** @deprecated 易与 UTF-8 混用导致 \xAA→C2 AA；请用 parseEscapeToBytes */
export function parseEscapeSequences(text) {
  const bytes = parseEscapeToBytes(text)
  let out = ''
  for (const b of bytes) out += String.fromCharCode(b)
  return out
}

export function buildRawSendHex({ text, isHex, parseEscape, lineEnding }) {
  const suffix = lineEnding && lineEnding !== 'none' ? SERIAL_LINE_ENDING_SUFFIX[lineEnding] || '' : ''
  if (isHex) {
    if (!isHexText(text)) return { ok: false, warn: HEX_INPUT_WARN }
    const bodyHex = normalizeHexDisplay(text)
    if (!cleanHex(text) && !suffix) return { ok: false, warn: '请输入数据' }
    let hex = bodyHex
    if (suffix) {
      const suffixHex = textToHex(suffix)
      hex = hex ? `${hex} ${suffixHex}` : suffixHex
    }
    return { ok: true, hex }
  }
  if (parseEscape) {
    const bytes = Array.from(parseEscapeToBytes(text || ''))
    if (suffix) bytes.push(...new TextEncoder().encode(suffix))
    if (!bytes.length) return { ok: false, warn: '请输入数据' }
    return { ok: true, hex: bytesToHex(bytes) }
  }
  let body = text || ''
  if (suffix) body += suffix
  if (!body) return { ok: false, warn: '请输入数据' }
  return { ok: true, hex: textToHex(body) }
}

/**
 * @param {object} entry
 * @param {{ hexMode?: boolean, style?: 'default'|'udp' }} opts
 *   style=udp 时消息头带 to/from peer（CAN/串口用 default）
 *   若 entry.frameIdHex 存在：正文显示为「帧ID : 数据」
 */
export function formatIoLogBlock(entry, { hexMode = true, style = 'default' } = {}) {
  const ts = entry.ts || ''
  const dir = (entry.dir || 'recv').toUpperCase() === 'SEND' ? 'SEND' : 'RECV'
  const arrow = dir === 'SEND' ? '>>>' : '<<<'
  const dataHex = normalizeHexDisplay(entry.hex || '')
  const frameIdHex = normalizeHexDisplay(entry.frameIdHex || '')
  const len = entry.len != null
    ? entry.len
    : dataHex.split(' ').filter(Boolean).length
  const mode = hexMode ? 'HEX' : 'ASCII'
  const peer = String(entry.peer || '').trim()
  let header = `[${ts}]# ${dir} ${mode}/${len} ${arrow}`
  // 有 peer 即显示来源（不依赖 style，避免刷新瞬间 style 未就绪导致冻住缺 from/to）
  if (peer) {
    const peerPart = dir === 'SEND' ? `to ${peer}` : `from ${peer}`
    header = `[${ts}]# ${dir} ${mode}/${len} ${peerPart} ${arrow}`
  }
  let body
  if (frameIdHex) {
    const dataPart = hexMode ? dataHex : hexToDisplayAscii(entry.hex || '')
    body = dataPart ? `${frameIdHex} : ${dataPart}` : `${frameIdHex} :`
  } else {
    body = hexMode ? dataHex : hexToDisplayAscii(entry.hex || '')
  }
  return `${header}\n${body}\n\n`
}
