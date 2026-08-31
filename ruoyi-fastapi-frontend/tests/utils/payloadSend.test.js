import { describe, expect, it } from 'vitest'
import { channelLabelFromDeviceId } from '@/utils/payloadSend'

describe('utils/payloadSend', () => {
  it('channelLabelFromDeviceId 识别通道类型', () => {
    expect(channelLabelFromDeviceId('can:0:0:0')).toBe('CAN')
    expect(channelLabelFromDeviceId('serial:COM3')).toBe('串口')
    expect(channelLabelFromDeviceId('udp:0.0.0.0:9000')).toBe('UDP')
    expect(channelLabelFromDeviceId('tcp:127.0.0.1:1')).toBe('TCP')
    expect(channelLabelFromDeviceId('')).toBe('')
  })
})
