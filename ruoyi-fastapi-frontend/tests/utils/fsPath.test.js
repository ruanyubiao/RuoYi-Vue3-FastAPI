import { describe, expect, it } from 'vitest'
import { baseNameAny, displayFsPath, fileExtAllowed, parentRelPath } from '@/utils/fsPath'

describe('fsPath 跨平台路径工具', () => {
  it('displayFsPath 原行为不变', () => {
    expect(displayFsPath('E:/data/a.bin')).toBe('E:\\data\\a.bin')
    expect(displayFsPath('/home/u/a.bin')).toBe('/home/u/a.bin')
    expect(displayFsPath('')).toBe('')
  })

  it('fileExtAllowed 先原样匹配，再按小写匹配', () => {
    expect(fileExtAllowed(['pdf', 'png'], 'pdf')).toBe(true)
    expect(fileExtAllowed(['pdf', 'png'], 'PDF')).toBe(true)
    expect(fileExtAllowed(['pdf'], 'exe')).toBe(false)
    expect(fileExtAllowed(undefined, 'pdf')).toBe(false)
  })

  it('baseNameAny 同时识别 / 与 \\', () => {
    expect(baseNameAny('http://h/profile/upload/a.pdf')).toBe('a.pdf')
    expect(baseNameAny('C:\\dir\\b.pdf')).toBe('b.pdf')
    expect(baseNameAny('c.pdf')).toBe('c.pdf')
    expect(baseNameAny(null)).toBe('')
  })

  it('parentRelPath 识别反斜杠并统一为 /', () => {
    expect(parentRelPath('a\\b\\c')).toBe('a/b')
    expect(parentRelPath('a/b/c')).toBe('a/b')
    expect(parentRelPath('a')).toBe('')
    expect(parentRelPath('')).toBe('')
  })
})
