import { describe, expect, it } from 'vitest'
import {
  baseNameAny,
  buildRecvBrowseDisplayPath,
  displayFsPath,
  fileExtAllowed,
  parentRelPath,
  toRecvBrowseDisplayPath
} from '@/utils/fsPath'

describe('fsPath 跨平台路径工具', () => {
  it('displayFsPath 原行为不变', () => {
    expect(displayFsPath('E:/data/a.bin')).toBe('E:\\data\\a.bin')
    expect(displayFsPath('/home/u/a.bin')).toBe('/home/u/a.bin')
    expect(displayFsPath('')).toBe('')
  })

  it('toRecvBrowseDisplayPath 映射上传/本地日志虚拟路径', () => {
    expect(
      toRecvBrowseDisplayPath(
        'E:/plat/vf_admin/upload_path/upload_logs_data_raw/camera_ctrl_serial_COM1_20260825_094027_980_recv.bin'
      )
    ).toBe('首页/上传文件/camera_ctrl_serial_COM1_20260825_094027_980_recv.bin')
    expect(
      toRecvBrowseDisplayPath(
        'E:\\plat\\logs_data\\raw\\2026\\09\\18\\camera_ctrl_serial_COM1_20260825_094027_980_recv.bin'
      )
    ).toBe('首页/本地日志/2026/09/18/camera_ctrl_serial_COM1_20260825_094027_980_recv.bin')
    expect(toRecvBrowseDisplayPath('首页/本地日志/a.bin')).toBe('首页/本地日志/a.bin')
  })

  it('buildRecvBrowseDisplayPath 按 root/rel/name 拼接', () => {
    expect(buildRecvBrowseDisplayPath('logs', '2026/09/18', 'a.bin')).toBe(
      '首页/本地日志/2026/09/18/a.bin'
    )
    expect(buildRecvBrowseDisplayPath('upload', '', 'a.bin')).toBe('首页/上传文件/a.bin')
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
