/**
 * 遥控指令搜索匹配。
 *
 * 使用方：BIU/XL 遥控、指令序列、相机、单板（同一套 Everything 精简语法）。
 * 匹配：orderMatchesFilter(order, 搜索框原文) → everything_filter.matchText。
 *
 * 命中范围（orderSearchText）：指令 id、name、各 component.title；不含 tip。
 */

import { matchText } from './everything_filter'

/** 指令树搜索框 placeholder，各 Vue 页用 :placeholder 引用。 */
export const TELECONTROL_ORDER_FILTER_PLACEHOLDER =
  '搜索：空格与、|或、!非、"短语"、*?'

/**
 * 搜索框是否有有效内容（trim 后非空）。用于自动展开指令树等，不参与匹配。
 *
 * @param {string} text
 * @returns {boolean}
 */
export function hasOrderFilter(text) {
  return String(text || '').trim().length > 0
}

/**
 * 拼出可搜索文本：id + name + 各参数 title（跳过空 title）。
 *
 * @param {{ id?: string, name?: string, component?: { title?: string }[] }} order
 * @returns {string}
 */
export function orderSearchText(order) {
  const parts = [order?.id || '', order?.name || '']
  for (const comp of order?.component || []) {
    const title = comp?.title
    if (title !== undefined && title !== null && String(title).trim() !== '') {
      parts.push(String(title))
    }
  }
  return parts.join(' ')
}

/**
 * 指令是否命中搜索框原文。空串 / 全空白 → true（不过滤）。
 *
 * @param {object} order
 * @param {string} filterText
 * @returns {boolean}
 */
export function orderMatchesFilter(order, filterText) {
  return matchText(orderSearchText(order), filterText)
}
