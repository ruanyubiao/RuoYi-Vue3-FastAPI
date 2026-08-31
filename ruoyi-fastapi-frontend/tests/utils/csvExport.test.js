import { describe, expect, it } from 'vitest'
import { buildAlignedSeriesTable, csvEscape, formatCsvDateTime } from '@/utils/csvExport'

describe('utils/csvExport', () => {
  it('formatCsvDateTime', () => {
    const ms = new Date(2026, 0, 2, 3, 4, 5, 6).getTime()
    expect(formatCsvDateTime(ms)).toBe('2026-01-02 03:04:05.006')
  })

  it('csvEscape 引号与逗号', () => {
    expect(csvEscape('a,b')).toBe('"a,b"')
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""')
    expect(csvEscape(null)).toBe('')
  })

  it('buildAlignedSeriesTable 时间对齐', () => {
    const seriesList = [
      { name: 'A', points: [[1000, 1], [2000, 2]] },
      { name: 'B', points: [[2000, 9]] }
    ]
    const { headers, rows } = buildAlignedSeriesTable(seriesList, { start: 0, end: 5000 })
    expect(headers).toEqual(['时间', 'A', 'B'])
    expect(rows).toHaveLength(2)
    expect(rows[0][1]).toBe(1)
    expect(rows[1][2]).toBe(9)
    expect(rows[0][2]).toBe('')
  })
})
