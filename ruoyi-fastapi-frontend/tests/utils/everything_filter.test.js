import { describe, expect, it } from 'vitest'
import {
  collapseOrSpaces,
  filterStrings,
  filterStringsWithIndex,
  hasActiveFilter,
  matchAnd,
  matchAndTerm,
  matchOne,
  matchOrTerm,
  matchText,
  normalizeQuery,
  prepareQuery,
  splitOrParts,
  tokenize
} from '@/utils/everything_filter'

const items = [
  'hello world',
  'hello python',
  'hello java',
  'test python',
  'main.py',
  'test.py',
  'K1501 通信使能',
  'K1502 驱动使能'
]

const cameraItems = [
  'K1001 开窗参数',
  'K1002 拍照模式',
  'K1003 开窗拍照联动',
  'K1004 指向星敏设置包',
  'K1005 其它指令',
  'K1006 指向 设置',
  'K1007 星敏 设置',
  'K1008 指向',
  'K1009 设置',
  'K1010 指向|星敏 设置'
]

describe('utils/everything_filter', () => {
  describe('normalizeQuery / prepareQuery', () => {
    it('中文弯引号→英文引号', () => {
      expect(normalizeQuery('\u201c指向|星敏 设置\u201d')).toBe('"指向|星敏 设置"')
    })

    it('中文问号？→英文 ?', () => {
      expect(normalizeQuery('K15？？')).toBe('K15??')
      expect(matchText('K1501', 'K15？？')).toBe(true)
      expect(matchText('K150', 'K15？？')).toBe(false)
    })

    it('引号外中文空格/NBSP→英文，引号内保留', () => {
      expect(normalizeQuery('开窗\u3000|\u3000拍照')).toBe('开窗 | 拍照')
      expect(normalizeQuery('开窗\u00a0拍照')).toBe('开窗 拍照')
      expect(normalizeQuery('"指向\u3000星敏"')).toBe('"指向\u3000星敏"')
    })

    it('| 两侧空格收掉；引号内 | 旁空格保留', () => {
      expect(collapseOrSpaces('开窗 | 拍照')).toBe('开窗|拍照')
      expect(collapseOrSpaces('"开窗 | 拍照"')).toBe('"开窗 | 拍照"')
      expect(prepareQuery('开窗\u3000|\u3000拍照')).toBe('开窗|拍照')
      expect(prepareQuery('指向|星敏 设置')).toBe('指向|星敏 设置')
      expect(prepareQuery('  姿态  俯仰  ')).toBe('姿态  俯仰')
    })
  })

  describe('tokenize / splitOrParts', () => {
    it('先收 | 空格再按空格 AND 分词', () => {
      expect(tokenize('开窗 | 拍照')).toEqual(['开窗|拍照'])
      expect(tokenize('指向|星敏 设置')).toEqual(['指向|星敏', '设置'])
      expect(tokenize('"hello world" python')).toEqual(['"hello world"', 'python'])
      expect(tokenize('"指向|星敏 设置"')).toEqual(['"指向|星敏 设置"'])
      expect(tokenize('a !b | c')).toEqual(['a', '!b|c'])
    })

    it('词内 OR 拆分并丢掉空分支', () => {
      expect(splitOrParts('开窗|拍照')).toEqual(['开窗', '拍照'])
      expect(splitOrParts('开窗|')).toEqual(['开窗'])
      expect(splitOrParts('|拍照')).toEqual(['拍照'])
      expect(splitOrParts('|')).toEqual([])
      expect(splitOrParts('a|b|c')).toEqual(['a', 'b', 'c'])
    })
  })

  describe('matchOne', () => {
    it('普通包含', () => {
      expect(matchOne('hello python', 'python')).toBe(true)
      expect(matchOne('hello java', 'python')).toBe(false)
      expect(matchOne('Hello', 'hello')).toBe(true)
      expect(matchOne('Hello', 'hello', false)).toBe(false)
    })

    it('双引号短语', () => {
      expect(matchOne('hello python world', '"hello python"')).toBe(true)
      expect(matchOne('hello world python', '"hello python"')).toBe(false)
    })

    it('通配符按子串', () => {
      expect(matchOne('test.py', '*.py')).toBe(true)
      expect(matchOne('main.py', 'test*')).toBe(false)
      expect(matchOne('K1501', 'K15??')).toBe(true)
      expect(matchOne('开窗拍照联动', '拍*')).toBe(true)
      expect(matchOne('开窗参数', '拍*')).toBe(false)
    })

    it('^ 开头 / $ 结尾', () => {
      expect(matchOne('K1501 使能', '^K15')).toBe(true)
      expect(matchOne('xK1501', '^K15')).toBe(false)
      expect(matchOne('main.py', '.py$')).toBe(true)
      expect(matchOne('main.py.bak', '.py$')).toBe(false)
    })

    it('空 pattern 恒真', () => {
      expect(matchOne('anything', '')).toBe(true)
      expect(matchOne('anything', '   ')).toBe(true)
    })
  })

  describe('matchOrTerm / matchAndTerm', () => {
    it('词内 OR', () => {
      expect(matchOrTerm('开窗参数', '开窗|拍照')).toBe(true)
      expect(matchOrTerm('拍照模式', '开窗|拍照')).toBe(true)
      expect(matchOrTerm('其它', '开窗|拍照')).toBe(false)
      expect(matchOrTerm('x', '|')).toBe(false)
    })

    it('NOT 与 NOT+OR', () => {
      expect(matchAndTerm('hello python', '!test')).toBe(true)
      expect(matchAndTerm('test python', '!test')).toBe(false)
      expect(matchAndTerm('指向参数', '!指向|星敏')).toBe(false)
      expect(matchAndTerm('星敏参数', '!指向|星敏')).toBe(false)
      expect(matchAndTerm('其它指令', '!指向|星敏')).toBe(true)
    })
  })

  describe('matchText / matchAnd', () => {
    it('空查询匹配全部', () => {
      expect(matchText('anything', '')).toBe(true)
      expect(matchText('anything', '   ')).toBe(true)
      expect(filterStrings(items, '')).toEqual(items)
    })

    it('AND', () => {
      expect(matchText('hello python', 'hello python')).toBe(true)
      expect(matchText('hello java', 'hello python')).toBe(false)
      expect(matchAnd('hello python', 'python !test')).toBe(true)
      expect(matchAnd('test python', 'python !test')).toBe(false)
    })

    it('OR 空分支不误匹配全部（开窗|）', () => {
      expect(matchText('hello java', '开窗|')).toBe(false)
      expect(matchText('开窗参数', '开窗|')).toBe(true)
      expect(matchText('hello', '|')).toBe(false)
      expect(matchText('hello', '|hello')).toBe(true)
    })

    it('开窗 | 拍照 两边都能命中', () => {
      expect(filterStrings(cameraItems, '开窗 | 拍照')).toEqual([
        'K1001 开窗参数',
        'K1002 拍照模式',
        'K1003 开窗拍照联动'
      ])
    })

    it('开窗 | 拍* 通配两边都能命中', () => {
      expect(filterStrings(cameraItems, '开窗 | 拍*')).toEqual([
        'K1001 开窗参数',
        'K1002 拍照模式',
        'K1003 开窗拍照联动'
      ])
      expect(matchText('K1002 拍照模式', '开窗 | 拍*')).toBe(true)
      expect(matchText('K1005 其它指令', '开窗 | 拍*')).toBe(false)
    })

    it('空格优先于 |：指向|星敏 设置 = (指向|星敏) AND 设置', () => {
      expect(matchText('K1006 指向 设置', '指向|星敏 设置')).toBe(true)
      expect(matchText('K1007 星敏 设置', '指向|星敏 设置')).toBe(true)
      expect(matchText('K1004 指向星敏设置包', '指向|星敏 设置')).toBe(true)
      expect(matchText('K1008 指向', '指向|星敏 设置')).toBe(false)
      expect(matchText('K1009 设置', '指向|星敏 设置')).toBe(false)
      expect(matchText('K1005 其它指令', '指向|星敏 设置')).toBe(false)
    })

    it('引号短语：整段匹配，内部 | 与空格都不拆', () => {
      expect(matchText('K1010 指向|星敏 设置', '"指向|星敏 设置"')).toBe(true)
      expect(matchText('K1010 指向|星敏 设置', '\u201c指向|星敏 设置\u201d')).toBe(true)
      expect(filterStrings(cameraItems, '"指向|星敏 设置"')).toEqual(['K1010 指向|星敏 设置'])
      expect(matchText('K1006 指向 设置', '"指向|星敏 设置"')).toBe(false)
    })

    it('中文空格写法的 OR 与英文空格等价', () => {
      expect(filterStrings(cameraItems, '开窗\u3000|\u3000拍照')).toEqual(
        filterStrings(cameraItems, '开窗 | 拍照')
      )
    })

    it('ignoreCase 可关闭', () => {
      expect(matchText('Hello Python', 'hello', { ignoreCase: true })).toBe(true)
      expect(matchText('Hello Python', 'hello', { ignoreCase: false })).toBe(false)
      expect(matchText('Hello Python', 'Hello', { ignoreCase: false })).toBe(true)
    })
  })

  describe('filterStrings', () => {
    it('按查询过滤', () => {
      expect(filterStrings(items, '*.py')).toEqual(['main.py', 'test.py'])
      expect(filterStrings(items, 'K15*')).toEqual(['K1501 通信使能', 'K1502 驱动使能'])
    })

    it('非数组 / 非字符串元素', () => {
      expect(filterStrings(null, 'a')).toEqual([])
      expect(filterStrings(undefined, 'a')).toEqual([])
      expect(filterStrings(['a', 1, null, 'ab'], 'a')).toEqual(['a', 'ab'])
    })

    it('filterStringsWithIndex', () => {
      expect(filterStringsWithIndex(items, 'test.py')).toEqual([{ index: 5, value: 'test.py' }])
      expect(filterStringsWithIndex(null, 'x')).toEqual([])
    })
  })

  describe('hasActiveFilter', () => {
    it('trim 后是否非空', () => {
      expect(hasActiveFilter('')).toBe(false)
      expect(hasActiveFilter('  ')).toBe(false)
      expect(hasActiveFilter('  x  ')).toBe(true)
      expect(hasActiveFilter('|')).toBe(true)
    })
  })
})
