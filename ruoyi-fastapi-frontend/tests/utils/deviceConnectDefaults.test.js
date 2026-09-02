import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/payload/device', () => ({
  getDeviceConnectDefaults: vi.fn()
}))

import {
  CAMERA_CONNECT_SOURCE,
  CONNECT_SOURCE_LABEL,
  cameraConnectSource,
  connectSourceLabel,
  isConnectCfgFieldLocked,
  isConnectCfgParserLocked,
  isConnectCfgParserNone,
  normalizeConnectParserId,
  toBaudChoices,
  toCanPreset,
  toSerialPreset,
  toUdpPreset,
  udpRemotePeerError
} from '@/utils/deviceConnectDefaults'
import { ASSEMBLER_CAN_BIU, ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU } from '@/utils/pipelineIds'

describe('utils/deviceConnectDefaults', () => {
  describe('connectSourceLabel', () => {
    it('已知 key 返回中文', () => {
      expect(connectSourceLabel('biu_can_a')).toBe(CONNECT_SOURCE_LABEL.biu_can_a)
    })

    it('空 source 返回 empty', () => {
      expect(connectSourceLabel('', '-')).toBe('-')
    })
  })

  describe('cameraConnectSource', () => {
    it('v16/v17 ctrl 与 image', () => {
      expect(cameraConnectSource('ctrl', 'v16')).toBe(CAMERA_CONNECT_SOURCE.v16.ctrl)
      expect(cameraConnectSource('image', 'v17')).toBe(CAMERA_CONNECT_SOURCE.v17.image)
    })
  })

  describe('isConnectCfgFieldLocked', () => {
    it('非空字符串为锁定', () => {
      expect(isConnectCfgFieldLocked('can_biu')).toBe(true)
      expect(isConnectCfgFieldLocked('')).toBe(false)
      expect(isConnectCfgFieldLocked(null)).toBe(false)
    })
  })

  describe('parser none', () => {
    it('none 锁定且归一化为空串', () => {
      expect(isConnectCfgParserNone('none')).toBe(true)
      expect(isConnectCfgParserLocked('none')).toBe(true)
      expect(normalizeConnectParserId('none')).toBe('')
      const p = toSerialPreset({ baudrate: 2000000, parserId: 'none' })
      expect(p.parserId).toBe('')
      expect(p.lockParser).toBe(true)
    })

    it('空 parserId 不锁定', () => {
      expect(isConnectCfgParserLocked('')).toBe(false)
      const p = toSerialPreset({ baudrate: 115200, parserId: '' })
      expect(p.lockParser).toBe(false)
    })
  })

  describe('udpRemotePeerError', () => {
    it('仅地址无端口合法', () => {
      expect(udpRemotePeerError('192.168.1.1', 0)).toBe('')
    })

    it('无地址有端口报错', () => {
      expect(udpRemotePeerError('', 9000)).toContain('远程地址')
    })

    it('非法端口', () => {
      expect(udpRemotePeerError('1.1.1.1', 70000)).toContain('端口无效')
    })
  })

  describe('toSerialPreset', () => {
    it('默认值与锁定字段', () => {
      const p = toSerialPreset({ baudrate: 921600, assemblerId: 'can_biu' })
      expect(p.baudrate).toBe(921600)
      expect(p.assemblerId).toBe('can_biu')
      expect(p.lockAssembler).toBe(true)
    })

    it('空 assembler 用透传', () => {
      const p = toSerialPreset({})
      expect(p.assemblerId).toBe(ASSEMBLER_PASSTHROUGH)
      expect(p.lockAssembler).toBe(false)
    })
  })

  describe('toUdpPreset', () => {
    it('解析端口与锁定', () => {
      const p = toUdpPreset({ localPort: 8000, remoteHost: '10.0.0.1', remotePort: 0, parserId: 'p1' })
      expect(p.localPort).toBe(8000)
      expect(p.remoteHost).toBe('10.0.0.1')
      expect(p.lockParser).toBe(true)
    })
  })

  describe('toCanPreset', () => {
    it('波特率与 fallback', () => {
      const p = toCanPreset({ baudRate: 250 }, { nodeAddrTo: 0x0d })
      expect(p.baudRate).toBe(250)
      expect(p.nodeAddrTo).toBe(0x0d)
      expect(p.assemblerId).toBe(ASSEMBLER_CAN_BIU)
      expect(p.parserId).toBe(PARSER_TM_CAN_BIU)
    })
  })

  describe('toBaudChoices', () => {
    it('从 baudChoices 数组生成选项', () => {
      const choices = toBaudChoices({ baudChoices: [115200, 921600] })
      expect(choices).toEqual([
        { value: 115200, label: '115200' },
        { value: 921600, label: '921600' }
      ])
    })
  })
})
