/**
 * 应用一轮 IO 日志。序号回绕（本批最大 seq 小于已显示水位）时整窗接上，避免传输信息假死。
 * @param {object[]} list
 * @param {number} lastSeq
 */
export function takeIoLogItems(list, lastSeq) {
  if (!Array.isArray(list) || !list.length) {
    return { items: [], nextSeq: lastSeq }
  }
  const seqs = list
    .map(i => Number(i?.seq))
    .filter(n => Number.isFinite(n) && n > 0)
  const prev = Number(lastSeq)
  const prevOk = Number.isFinite(prev) && prev > 0 ? prev : 0
  const maxSeq = seqs.length ? Math.max(...seqs) : prevOk
  const rewind = seqs.length > 0 && maxSeq < prevOk
  const items = rewind
    ? list
    : list.filter(i => i?.seq == null || !Number.isFinite(Number(i.seq)) || Number(i.seq) > prevOk)
  return { items, nextSeq: maxSeq || prevOk }
}
