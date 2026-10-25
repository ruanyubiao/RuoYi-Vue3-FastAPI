import { describe, expect, it } from 'vitest'
import {
  DATE_FORMATS,
  U32_MAX,
  WEEK_SECONDS,
  dateFormatRows,
  formatProtocolValue,
  parseDateInput,
  parseProtocolValue,
  protocolToUnixMs
} from '@/utils/timeconv'

function rowValue(rows, label) {
  return rows.find(row => row.label === label)?.value
}

describe('utils/timeconv 协议字段', () => {
  it('HEX 空和 0 显示 00；非零按字段宽度与端序显示', () => {
    expect(formatProtocolValue(0, 'dec')).toBe('0')
    expect(formatProtocolValue(0, 'be')).toBe('00')
    expect(formatProtocolValue(0, 'le')).toBe('00')
    expect(formatProtocolValue(0x12345678, 'be')).toBe('12345678')
    expect(formatProtocolValue(0x12345678, 'le')).toBe('78563412')
    expect(formatProtocolValue(WEEK_SECONDS, 'be', 6)).toBe('093A80')
    expect(formatProtocolValue(WEEK_SECONDS, 'le', 6)).toBe('803A09')
    expect(formatProtocolValue(999, 'be', 4)).toBe('03E7')
    expect(formatProtocolValue(999, 'le', 4)).toBe('E703')
    expect(formatProtocolValue(1, 'be', 4)).toBe('0001')
    expect(formatProtocolValue(1, 'le', 4)).toBe('0100')
  })

  it('HEX 解析先按端序解释，再对字节左补零', () => {
    expect(parseProtocolValue('', 'be')).toBe(0)
    expect(parseProtocolValue('0', 'le')).toBe(0)
    expect(parseProtocolValue('01', 'be')).toBe(1)
    expect(parseProtocolValue('01', 'le')).toBe(1)
    expect(parseProtocolValue('12345678', 'be')).toBe(0x12345678)
    expect(parseProtocolValue('78563412', 'le')).toBe(0x12345678)
    expect(parseProtocolValue('00 00 00 01', 'be')).toBe(1)
  })

  it('HEX 超过 8 位、非法字符与字段上限立刻报错', () => {
    expect(() => parseProtocolValue('123456789', 'be')).toThrow(/8 位/)
    expect(() => parseProtocolValue('GG', 'be')).toThrow(/HEX/)
    expect(() => parseProtocolValue(String(U32_MAX + 1), 'dec')).toThrow(/范围/)
    expect(() => parseProtocolValue('1000', 'dec', 999, '毫秒')).toThrow(/0 ~ 999/)
    expect(() => parseProtocolValue(String(WEEK_SECONDS + 1), 'dec', WEEK_SECONDS, '周内秒')).toThrow(
      /0 ~ 604800/
    )
    expect(() => parseProtocolValue('00093A81', 'be', WEEK_SECONDS, '周内秒')).toThrow(/0 ~ 604800/)
    expect(parseProtocolValue(String(WEEK_SECONDS), 'dec', WEEK_SECONDS, '周内秒')).toBe(WEEK_SECONDS)
    expect(parseProtocolValue('00093A80', 'be', WEEK_SECONDS, '周内秒')).toBe(WEEK_SECONDS)
    expect(parseProtocolValue('4294967295', 'dec')).toBe(U32_MAX)
  })

  it('纪元 + 周 + 周内秒 + 毫秒合成 Unix 毫秒', () => {
    expect(protocolToUnixMs({ epochUtcSec: 0, week: 0, sow: 0, ms: 0 })).toBe(0)
    expect(protocolToUnixMs({ epochUtcSec: 1577836800, week: 0, sow: 0, ms: 0 })).toBe(1577836800000)
    expect(protocolToUnixMs({ epochUtcSec: 0, week: 1, sow: 2, ms: 3 })).toBe(604802003)
  })

  it('毫秒/周内秒越界、字段不属于合法范围或结果超出 Date 范围时报错', () => {
    expect(() => protocolToUnixMs({ epochUtcSec: 0, week: 0, sow: 0, ms: 1000 })).toThrow(/0 ~ 999/)
    expect(() => protocolToUnixMs({ epochUtcSec: 0, week: 0, sow: WEEK_SECONDS + 1, ms: 0 })).toThrow(
      /0 ~ 604800/
    )
    expect(() => protocolToUnixMs({ epochUtcSec: 0, week: -1, sow: 0, ms: 0 })).toThrow(/范围/)
    expect(() => protocolToUnixMs({ epochUtcSec: 0, week: U32_MAX, sow: WEEK_SECONDS, ms: 999 })).toThrow(
      /日期范围/
    )
  })
})

describe('utils/timeconv 日期转换', () => {
  const date = new Date('2024-01-02T03:04:05.678Z')

  it('格式表为需求 10 行（含备注），不含 Mongo / Excel', () => {
    const rows = dateFormatRows(date)
    expect(rows).toHaveLength(10)
    expect(DATE_FORMATS.map(item => item.label)).toEqual([
      'JS 本地日期时间',
      'JS 本地化日期时间',
      'ISO 8601（UTC）',
      'ISO 8601',
      'ISO 9075',
      'RFC 3339',
      'RFC 7231',
      'UTC 日期时间',
      'Unix 时间戳（秒）',
      'Unix 时间戳（毫秒）'
    ])
    expect(DATE_FORMATS.map(item => item.note)).toEqual([
      'Date.toString()，按本地时区显示',
      'Date.toLocaleString()，受系统区域和语言设置影响',
      'Date.toISOString()，使用 UTC，Z 表示 UTC',
      '国际标准日期时间格式，可包含时区偏移',
      'SQL 常见日期时间表示形式，不包含时区标记',
      '互联网日期时间规范，支持时区偏移和小数秒',
      'HTTP 日期格式，使用 GMT，精度为秒',
      'Date.toUTCString()，以 UTC 格式显示',
      '从 Unix 纪元起算的秒数，通常为 10 位',
      '从 Unix 纪元起算的毫秒数，通常为 13 位'
    ])
    expect(rows.every(row => row.note)).toBe(true)
    expect(rows.some(row => /mongo|excel/i.test(row.label))).toBe(false)
  })

  it('ISO / RFC / Unix 结果抽样', () => {
    const local = new Date(2024, 0, 2, 3, 4, 5, 123)
    const rows = dateFormatRows(local)
    expect(rowValue(rows, 'ISO 8601（UTC）')).toBe(local.toISOString())
    const isoLocal = rowValue(rows, 'ISO 8601')
    expect(isoLocal).toBe(rowValue(rows, 'RFC 3339'))
    expect(isoLocal).toMatch(/^2024-01-02T03:04:05\.123(Z|[+-]\d{2}:\d{2})$/)
    expect(rowValue(rows, 'ISO 9075')).toBe('2024-01-02 03:04:05.123')
    expect(rowValue(rows, 'JS 本地化日期时间')).toBe(local.toLocaleString())
    const utcRows = dateFormatRows(date)
    expect(rowValue(utcRows, 'RFC 7231')).toBe('Tue, 02 Jan 2024 03:04:05 GMT')
    expect(rowValue(utcRows, 'UTC 日期时间')).toBe(date.toUTCString())
    expect(rowValue(utcRows, 'Unix 时间戳（秒）')).toBe('1704164645')
    expect(rowValue(utcRows, 'Unix 时间戳（毫秒）')).toBe('1704164645678')
  })

  it('ISO 9075 使用本地时间；日期时间可往返解析', () => {
    const local = new Date(2024, 0, 2, 3, 4, 5)
    expect(rowValue(dateFormatRows(local), 'ISO 9075')).toBe('2024-01-02 03:04:05.000')
    const got = parseDateInput('2024-01-02 03:04:05')
    expect(got.date?.getTime()).toBe(local.getTime())
  })

  it('纯数字按位数区分秒和毫秒，计算结果可强制按毫秒', () => {
    expect(parseDateInput('').date).toBeNull()
    expect(parseDateInput('1577836800').date?.toISOString()).toBe('2020-01-01T00:00:00.000Z')
    expect(parseDateInput('15778368000').date?.getTime()).toBe(15778368000)
    expect(parseDateInput('1577836800000').date?.toISOString()).toBe('2020-01-01T00:00:00.000Z')
    expect(parseDateInput('604802003', { unit: 'ms' }).date?.getTime()).toBe(604802003)
    expect(parseDateInput('not-a-date').error).toBeTruthy()
  })
})
