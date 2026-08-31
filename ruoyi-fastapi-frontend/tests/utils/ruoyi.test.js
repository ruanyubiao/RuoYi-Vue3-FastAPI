import { describe, expect, it } from 'vitest'
import {
  addDateRange,
  blobValidate,
  getNormalPath,
  handleTree,
  parseStrEmpty,
  parseTime,
  selectDictLabel,
  selectDictLabels,
  tansParams
} from '@/utils/ruoyi'

describe('utils/ruoyi', () => {
  it('parseTime 10 位秒与自定义格式', () => {
    expect(parseTime(1609459200, '{y}-{m}-{d}')).toBe('2021-01-01')
    expect(parseTime(null)).toBeNull()
  })

  it('addDateRange 默认与自定义 prop', () => {
    expect(addDateRange({}, ['2021-01-01', '2021-01-02'])).toEqual({
      beginTime: '2021-01-01',
      endTime: '2021-01-02'
    })
    expect(addDateRange({}, ['a', 'b'], 'Date')).toEqual({ beginDate: 'a', endDate: 'b' })
  })

  it('selectDictLabel / selectDictLabels', () => {
    const dict = [
      { label: '男', value: '0' },
      { label: '女', value: '1' }
    ]
    expect(selectDictLabel(dict, '1')).toBe('女')
    expect(selectDictLabel(dict, '9')).toBe('9')
    expect(selectDictLabels(dict, '0,1')).toBe('男,女')
  })

  it('handleTree 扁平转树', () => {
    const flat = [
      { id: 1, parentId: 0, name: 'root' },
      { id: 2, parentId: 1, name: 'child' }
    ]
    const tree = handleTree(flat, 'id', 'parentId')
    expect(tree).toHaveLength(1)
    expect(tree[0].children[0].name).toBe('child')
  })

  it('tansParams 跳过空值', () => {
    expect(tansParams({ a: 1, b: null, c: '' })).toContain('a=1')
    expect(tansParams({ a: 1, b: null, c: '' })).not.toContain('b=')
  })

  it('getNormalPath 去尾斜杠', () => {
    expect(getNormalPath('/a/b/')).toBe('/a/b')
    expect(getNormalPath('/a/b//')).toBe('/a/b')
  })

  it('parseStrEmpty / blobValidate', () => {
    expect(parseStrEmpty(undefined)).toBe('')
    expect(parseStrEmpty('null')).toBe('')
    expect(blobValidate({ type: 'application/json' })).toBe(false)
    expect(blobValidate({ type: 'application/octet-stream' })).toBe(true)
  })
})
