/**
 * CSV 导出通用工具（可被任意页面复用）
 */

/** @param {number} ms */
export function formatCsvDateTime(ms) {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return String(ms)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

export function csvEscape(val) {
  const s = val == null ? '' : String(val)
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

/**
 * 下载文本文件（默认 CSV）
 * @param {string} filename
 * @param {string} text
 * @param {string} [mime]
 */
export function downloadTextFile(filename, text, mime = 'text/csv;charset=utf-8') {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * 将「多条 [t,v] 点列」按时间并对齐为表格。
 * 某个时间点若所有曲线都没数据则丢弃；部分有数据时缺测为空串。
 *
 * @param {Array<{ name: string, points: Array<[number, any]> }>} seriesList
 * @param {{ start: number, end: number, timeHeader?: string, formatTime?: (ms:number)=>string }} range
 * @returns {{ headers: string[], rows: any[][] }}
 */
export function buildAlignedSeriesTable(seriesList, range) {
  const { start, end, timeHeader = '时间', formatTime = formatCsvDateTime } = range || {}
  const maps = (seriesList || []).map(s => {
    const m = new Map()
    for (const p of s.points || []) {
      const t = p[0]
      if (t >= start && t <= end) m.set(t, p[1])
    }
    return m
  })
  const timeSet = new Set()
  for (const m of maps) {
    for (const t of m.keys()) timeSet.add(t)
  }
  const times = Array.from(timeSet).sort((a, b) => a - b)
  const headers = [timeHeader, ...(seriesList || []).map(s => s.name)]
  const rows = times.map(t => {
    const cells = [formatTime(t)]
    for (const m of maps) cells.push(m.has(t) ? m.get(t) : '')
    return cells
  })
  return { headers, rows }
}

/**
 * 生成带 BOM 的 CSV 文本并触发下载
 * @param {{ headers: string[], rows: any[][], filename: string }} payload
 */
export function exportCsvFile({ headers, rows, filename }) {
  const lines = [
    headers.map(csvEscape).join(','),
    ...rows.map(r => r.map(csvEscape).join(','))
  ]
  const csv = `\uFEFF${lines.join('\r\n')}`
  downloadTextFile(filename, csv)
  return { rowCount: rows.length, colCount: headers.length }
}
