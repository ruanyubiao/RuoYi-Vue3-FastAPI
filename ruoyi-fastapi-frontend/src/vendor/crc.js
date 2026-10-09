/**
 * CRC 参数表与计算。参数对齐 crc-calc.com / Catalogue of parametrised CRC algorithms。
 * 标准校验串为 ASCII ``123456789``。
 */

const MASK8 = 0xff
const MASK16 = 0xffff
const MASK32 = 0xffffffff

function maskOf(width) {
  if (width === 8) return MASK8
  if (width === 16) return MASK16
  return MASK32
}

function reflect(value, bits) {
  let out = 0
  for (let i = 0; i < bits; i++) {
    if (value & (1 << i)) out |= 1 << (bits - 1 - i)
  }
  return out
}

function crcBytewise(bytes, model) {
  const { width, poly, init, refin, refout, xorout } = model
  const mask = maskOf(width)
  const top = 1 << (width - 1)
  let crc = init & mask
  for (let i = 0; i < bytes.length; i++) {
    let b = bytes[i] & 0xff
    if (refin) b = reflect(b, 8)
    crc ^= b << (width - 8)
    crc &= mask
    for (let bit = 0; bit < 8; bit++) {
      if (crc & top) crc = ((crc << 1) ^ poly) & mask
      else crc = (crc << 1) & mask
    }
  }
  if (refout) crc = reflect(crc, width)
  return ((crc ^ xorout) & mask) >>> 0
}

/** Popular 12 种 CRC。id 为叶子勾选缓存键。 */
export const CRC_ALGORITHMS = [
  {
    id: 'crc8-autosar',
    name: 'CRC-8/AUTOSAR',
    group: 'CRC-8',
    width: 8,
    poly: 0x2f,
    init: 0xff,
    refin: false,
    refout: false,
    xorout: 0xff,
    check: 0xdf
  },
  {
    id: 'crc8-sae-j1850',
    name: 'CRC-8/SAE-J1850',
    group: 'CRC-8',
    width: 8,
    poly: 0x1d,
    init: 0xff,
    refin: false,
    refout: false,
    xorout: 0xff,
    check: 0x4b
  },
  {
    id: 'crc8-maxim-dow',
    name: 'CRC-8/MAXIM-DOW',
    group: 'CRC-8',
    width: 8,
    poly: 0x31,
    init: 0x00,
    refin: true,
    refout: true,
    xorout: 0x00,
    check: 0xa1
  },
  {
    id: 'crc8-rohc',
    name: 'CRC-8/ROHC',
    group: 'CRC-8',
    width: 8,
    poly: 0x07,
    init: 0xff,
    refin: true,
    refout: true,
    xorout: 0x00,
    check: 0xd0
  },
  {
    id: 'crc16-modbus',
    name: 'CRC-16/MODBUS',
    group: 'CRC-16',
    width: 16,
    poly: 0x8005,
    init: 0xffff,
    refin: true,
    refout: true,
    xorout: 0x0000,
    check: 0x4b37
  },
  {
    id: 'crc16-ccitt-false',
    name: 'CRC-16/CCITT-FALSE',
    group: 'CRC-16',
    width: 16,
    poly: 0x1021,
    init: 0xffff,
    refin: false,
    refout: false,
    xorout: 0x0000,
    check: 0x29b1
  },
  {
    id: 'crc16-xmodem',
    name: 'CRC-16/XMODEM',
    group: 'CRC-16',
    width: 16,
    poly: 0x1021,
    init: 0x0000,
    refin: false,
    refout: false,
    xorout: 0x0000,
    check: 0x31c3
  },
  {
    id: 'crc16-arc',
    name: 'CRC-16/ARC',
    group: 'CRC-16',
    width: 16,
    poly: 0x8005,
    init: 0x0000,
    refin: true,
    refout: true,
    xorout: 0x0000,
    check: 0xbb3d
  },
  {
    id: 'crc32-iso-hdlc',
    name: 'CRC-32/ISO-HDLC',
    group: 'CRC-32',
    width: 32,
    poly: 0x04c11db7,
    init: 0xffffffff,
    refin: true,
    refout: true,
    xorout: 0xffffffff,
    check: 0xcbf43926 >>> 0
  },
  {
    id: 'crc32-iscsi',
    name: 'CRC-32C',
    group: 'CRC-32',
    width: 32,
    poly: 0x1edc6f41,
    init: 0xffffffff,
    refin: true,
    refout: true,
    xorout: 0xffffffff,
    check: 0xe3069283 >>> 0
  },
  {
    id: 'crc32-mpeg2',
    name: 'CRC-32/MPEG-2',
    group: 'CRC-32',
    width: 32,
    poly: 0x04c11db7,
    init: 0xffffffff,
    refin: false,
    refout: false,
    xorout: 0x00000000,
    check: 0x0376e6e7 >>> 0
  },
  {
    id: 'crc32-bzip2',
    name: 'CRC-32/BZIP2',
    group: 'CRC-32',
    width: 32,
    poly: 0x04c11db7,
    init: 0xffffffff,
    refin: false,
    refout: false,
    xorout: 0xffffffff,
    check: 0xfc891918 >>> 0
  }
]

const BY_ID = Object.fromEntries(CRC_ALGORITHMS.map(a => [a.id, a]))

export function getCrcAlgorithm(id) {
  return BY_ID[id] || null
}

export function computeCrc(id, bytes) {
  const model = getCrcAlgorithm(id)
  if (!model) throw new Error(`未知 CRC 算法: ${id}`)
  return crcBytewise(bytes, model)
}

/** 结果格式：无 0x/0b 前缀；HEX 大写按位宽补零；BIN 按位宽补零、每 8 位一组。 */
export function formatCrcValue(value, width) {
  const n = Number(value) >>> 0
  const hexLen = width / 4
  const hex = n.toString(16).toUpperCase().padStart(hexLen, '0')
  const bin = n.toString(2).padStart(width, '0').replace(/(.{8})/g, '$1 ').trim()
  return {
    hex,
    dec: String(n),
    oct: n.toString(8),
    bin
  }
}

export function crcAlgoTree() {
  const groups = ['CRC-8', 'CRC-16', 'CRC-32']
  return groups.map(g => ({
    id: g,
    label: g,
    children: CRC_ALGORITHMS.filter(a => a.group === g).map(a => ({
      id: a.id,
      label: a.name
    }))
  }))
}

/** 累加校验。low 取低位；cpl 为补码（再累加后和为 0）；not 为按位取反。 */
export const SUM_ALGORITHMS = [
  { id: 'sum8', name: 'SUM8', group: 'SUM', width: 8, kind: 'low' },
  { id: 'sum16', name: 'SUM16', group: 'SUM', width: 16, kind: 'low' },
  { id: 'sum32', name: 'SUM32', group: 'SUM', width: 32, kind: 'low' },
  { id: 'sum8-cpl', name: 'SUM8-CPL', group: 'SUM', width: 8, kind: 'cpl' },
  { id: 'sum16-cpl', name: 'SUM16-CPL', group: 'SUM', width: 16, kind: 'cpl' },
  { id: 'sum8-not', name: 'SUM8-NOT', group: 'SUM', width: 8, kind: 'not' },
  { id: 'sum16-not', name: 'SUM16-NOT', group: 'SUM', width: 16, kind: 'not' }
]

function byteSum(bytes) {
  let sum = 0
  for (let i = 0; i < bytes.length; i++) sum += bytes[i] & 0xff
  return sum
}

function maskSum(sum, width) {
  if (width === 8) return sum & 0xff
  if (width === 16) return sum & 0xffff
  return sum >>> 0
}

export function sum8(bytes) {
  return maskSum(byteSum(bytes), 8)
}

export function computeSum(id, bytes) {
  const algo = SUM_ALGORITHMS.find(a => a.id === id)
  if (!algo) throw new Error(`未知累加算法: ${id}`)
  const low = maskSum(byteSum(bytes), algo.width)
  if (algo.kind === 'cpl') return maskSum(-low, algo.width)
  if (algo.kind === 'not') return maskSum(~low, algo.width)
  return low
}

export function getChecksumAlgorithm(id) {
  return SUM_ALGORITHMS.find(a => a.id === id) || getCrcAlgorithm(id)
}

export function computeChecksum(id, bytes) {
  if (SUM_ALGORITHMS.some(a => a.id === id)) return computeSum(id, bytes)
  return computeCrc(id, bytes)
}

export function checksumAlgoTree() {
  return [
    {
      id: 'SUM',
      label: 'SUM',
      children: SUM_ALGORITHMS.map(a => ({ id: a.id, label: a.name }))
    },
    ...crcAlgoTree()
  ]
}

export const CHECKSUM_ALGORITHMS = [...SUM_ALGORITHMS, ...CRC_ALGORITHMS]
